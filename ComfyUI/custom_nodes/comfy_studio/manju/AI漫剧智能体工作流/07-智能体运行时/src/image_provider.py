# -*- coding: utf-8 -*-
"""图像生成 Provider 抽象层（蓝图 §二十二「未来模型适配」）。

    「系统不要绑定单一图片模型。Prompt Agent 输出统一格式，
      由 Provider 决定具体 API。」

内置
────
  mock      —— **零依赖**（zlib+struct 手写 PNG），产出真实可打开的占位图。
               目的：让整条流水线在**没有任何 API Key 的电脑上也能跑通**。
  openai    —— OpenAI 兼容 `POST {base_url}/images/generations`
               （OpenAI / 智谱 CogView / 通义万相兼容模式 / 各类网关）
  stability —— Stability AI `stable-image/generate/core`
  comfyui   —— **驱动本机 ComfyUI**：`POST /prompt` 入队 → 轮询 `/history` → `/view` 取图。
               与上面两个的**根本差别**：那两个是"给文字、还你图"的黑盒，
               这个要你**自带一张工作流节点图**，本 Provider 只往里注入四处
               （正向词 / 负向词 / 尺寸 / seed），其余节点照工作流原样。
               ComfyUI 在本机开着就能用，**不需要任何 API Key**。

依赖策略
────────
  mock / comfyui 只用标准库 → **装完 Python 就能跑**；
  openai / stability 需要 requests，**只在真正调用时 import** →
  没装也不影响 mock，不会因缺依赖导致项目起不来。
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import struct
import time
import urllib.parse
import urllib.request
import zlib
from abc import ABC, abstractmethod
from dataclasses import dataclass


# ── 手写 PNG（零依赖）──

def _chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def write_png(path: str, width: int, height: int, pixel_fn) -> None:
    """把 `pixel_fn(x, y) -> (r, g, b)` 写成 PNG。纯标准库，无需 Pillow。"""
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        row = bytearray()
        for x in range(width):
            r, g, b = pixel_fn(x, y)
            row += bytes((r & 255, g & 255, b & 255))
        raw += row
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    blob = (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + _chunk(b"IEND", b""))
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as f:
        f.write(blob)


def png_size(path: str) -> tuple[int, int] | tuple[None, None]:
    """读 PNG 的宽高（只读头部，不解码全图）。

    用途：核验产出图是否真是**预期尺寸**（尺寸错了多半是 Provider 参数没生效）。
    ⚠️ 只支持 PNG —— 本项目只用 PNG。
    """
    try:
        with open(path, "rb") as f:
            head = f.read(24)
        if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
            return None, None
        w = int.from_bytes(head[16:20], "big")
        h = int.from_bytes(head[20:24], "big")
        return w, h
    except Exception:                                                # noqa: BLE001
        return None, None


@dataclass
class ProviderInfo:
    name: str
    available: bool
    reason: str = ""
    needs_key: bool = True


class ImageProvider(ABC):
    name = "base"

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or {}

    @abstractmethod
    def generate(self, *, prompt: str, negative_prompt: str = "",
                 width: int = 1024, height: int = 1024,
                 out_path: str = "", n: int = 1,
                 reference: str | None = None) -> list[str]:
        ...

    def info(self) -> ProviderInfo:
        return ProviderInfo(self.name, True)


def resolve_reference(reference: str | None) -> tuple[str, str]:
    """校验参考图，返回 `(绝对路径, 问题描述)`；无参考图时返回 `("", "")`。

    ⚠️ **参考图不存在时必须报错，不能静默降级成纯文字生成** ——
    工作流 §4.1 的警告正是「各角度独立从文字生成 → **空间必然漂移**」。
    若我们把"挂图失败"悄悄吞掉，用户会拿到六张各自为政的图却以为已按铁则执行
    —— 这是本项目反复强调的那类失败：**静默比报错更难查**。
    """
    if not reference:
        return "", ""
    p = os.path.abspath(reference)
    if not os.path.isfile(p):
        return "", (f"参考图不存在：{reference} —— 铁则②要求以基图为 reference_image，"
                    f"缺失时空间/形象会漂移；请先渲染基图，或显式接受无参考图")
    if png_size(p) == (None, None):
        return "", f"参考图不是可读的 PNG：{reference}"
    return p, ""


class MockProvider(ImageProvider):
    """不调用网络，手写一张**真实可打开的 PNG**。

    为什么不是「返回假路径」：那样下游看不到图，无法验证落盘与预览链路。
    这里产出的是真图 —— 按资产 ID 派生配色，并画出 16:9 资产图的版式提示
    （左 32% 分隔线 = 特写区，右侧三条三分线 = 三视图区）。

    ⚠️ **性能**：朴素实现是「逐像素调函数」（1024×576 = 59 万次 Python 调用），
    实测慢到不可接受（命令行会卡住）。故改为：
      ① 先算**低分辨率图案**（≈ 256×144）
      ② **最近邻放大**，并用「行缓存 + `bytes * n`」避免逐像素拼接
      ③ 版式线在**最终分辨率**上以整行/整列赋值叠加
    结果：像素计算量降约 16 倍，且无逐像素 Python 循环。
    """

    name = "mock"

    def generate(self, *, prompt: str, negative_prompt: str = "",
                 width: int = 1024, height: int = 1024,
                 out_path: str = "", n: int = 1,
                 reference: str | None = None) -> list[str]:
        ref_path, prob = resolve_reference(reference)
        if prob:
            raise FileNotFoundError(prob)
        # ⭐ 参考图**参与配色**：于是"参考图是否真的传进来了"可以**用产物验证**
        #    （同一个 prompt、有/无参考图 → 两张图像素不同）。不这么做的话，
        #    mock 下的参考图只存在于注释里，等于没测。
        ref_fp = hashlib.sha256(open(ref_path, "rb").read()).hexdigest()[:16] \
            if ref_path else ""
        seed = hashlib.sha256(
            (prompt + negative_prompt + ref_fp).encode("utf-8")).digest()
        base = (seed[0], seed[1], seed[2])
        accent = (seed[3], seed[4], seed[5])
        gray = bytes((245, 245, 245))
        edge = bytes((30, 30, 30))

        scale = max(1, (width + 255) // 256)          # 放大倍数
        bw, bh = max(1, width // scale), max(1, height // scale)

        # ① 低分辨率渐变
        small: list[bytes] = []
        for y in range(bh):
            fy = y / max(1, bh - 1)
            row = bytearray()
            for x in range(bw):
                t = (x / max(1, bw - 1)) * 0.6 + fy * 0.4
                row += bytes((int(base[0] * (1 - t) + accent[0] * t),
                              int(base[1] * (1 - t) + accent[1] * t),
                              int(base[2] * (1 - t) + accent[2] * t)))
            small.append(bytes(row))

        # ② 放大（行缓存 —— 同一源行只拼一次）
        row_cache: dict[int, bytearray] = {}
        for sy in range(bh):
            row = bytearray()
            srow = small[sy]
            for x in range(bw):
                row += srow[x * 3:x * 3 + 3] * scale
            row_cache[sy] = row

        # ③ 叠加版式线（最终分辨率）
        thirds_x = (width // 3, 2 * width // 3)
        thirds_y = (height // 3, 2 * height // 3)
        split_x = int(width * 0.32)
        raw = bytearray()
        for y in range(height):
            sy = min(y // scale, bh - 1)
            if y < 2 or y >= height - 2 or y in thirds_y:
                row = bytearray(edge if y < 2 or y >= height - 2
                                else bytes((200, 210, 220)) * width)
            else:
                row = bytearray(row_cache[sy])
            for cx in (split_x,) + thirds_x:
                row[cx * 3:cx * 3 + 3] = gray
            if ref_path and 6 <= y < 6 + max(3, height // 12):
                # ⭐ 参考图标记带（左上白条）—— 一眼可辨"这张是挂了参考图的"。
                #    与"配色参与"一起，使参考图链路**可被产物证明**。
                row[6 * 3:(width // 5) * 3] = bytes((255, 255, 255)) * (width // 5 - 6)
            raw.append(0)                              # filter type
            raw += row

        ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        blob = (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
                + _chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + _chunk(b"IEND", b""))

        paths = []
        for i in range(max(1, n)):
            p = out_path if n == 1 else f"{os.path.splitext(out_path)[0]}_{i + 1}.png"
            os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
            with open(p, "wb") as f:
                f.write(blob)
            paths.append(p)
        return paths

    def info(self) -> ProviderInfo:
        return ProviderInfo(self.name, True,
                            "零依赖占位图（不调网络，用于验证流水线；支持参考图）",
                            needs_key=False)


class OpenAICompatProvider(ImageProvider):
    name = "openai"

    def __init__(self, cfg: dict | None = None):
        super().__init__(cfg)
        self.api_key = (self.cfg.get("api_key") or os.getenv("IMAGE_API_KEY")
                        or os.getenv("OPENAI_API_KEY") or "")
        self.base_url = (self.cfg.get("base_url") or os.getenv("IMAGE_BASE_URL")
                         or "https://api.openai.com/v1").rstrip("/")
        self.model = self.cfg.get("model") or os.getenv("IMAGE_MODEL") or "gpt-image-1"

    def generate(self, *, prompt: str, negative_prompt: str = "",
                 width: int = 1024, height: int = 1024,
                 out_path: str = "", n: int = 1,
                 reference: str | None = None) -> list[str]:
        if not self.api_key:
            raise RuntimeError("缺少 API Key：请设置环境变量 IMAGE_API_KEY")
        try:
            import requests
        except ImportError as e:
            raise RuntimeError("需要 requests：pip install requests") from e

        ref, prob = resolve_reference(reference)
        if prob:
            raise FileNotFoundError(prob)

        full = prompt
        if negative_prompt:
            # 部分兼容网关不认 negative 字段 → 併入正文，保证约束不丢
            full = f"{prompt}\n\nAvoid: {negative_prompt}"

        if ref:
            # ⭐ 参考图走**真实的图生图接口**：`POST /images/edits`（multipart）。
            #    ⚠️ 不手写 Content-Type —— requests 传 `files=` 时会自己带 boundary，
            #    手动设置反而会破坏 multipart 解析。
            #    ⚠️ 字段名各网关不一（OpenAI gpt-image-1 用 `image[]`，
            #    dall-e-2 用 `image`）→ 可配置，默认取当前合约。
            field = self.cfg.get("reference_field", "image[]")
            with open(ref, "rb") as fh:
                blob = fh.read()
            data = {"model": self.model, "prompt": full,
                    "size": f"{width}x{height}", "n": str(n)}
            for k in ("input_fidelity", "strength"):
                if self.cfg.get(k):
                    data[k] = str(self.cfg[k])
            resp = requests.post(
                f"{self.base_url}{self.cfg.get('edit_path', '/images/edits')}",
                headers={"Authorization": f"Bearer {self.api_key}"},
                files={field: (os.path.basename(ref), blob, "image/png")},
                data=data,
                timeout=self.cfg.get("timeout", 300))
        else:
            resp = requests.post(
                f"{self.base_url}/images/generations",
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"},
                json={"model": self.model, "prompt": full,
                      "size": f"{width}x{height}", "n": n},
                timeout=self.cfg.get("timeout", 300))
        resp.raise_for_status()
        data = resp.json()

        paths = []
        for i, item in enumerate(data.get("data", [])):
            p = out_path if n == 1 else f"{os.path.splitext(out_path)[0]}_{i + 1}.png"
            os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
            if item.get("b64_json"):
                with open(p, "wb") as f:
                    f.write(base64.b64decode(item["b64_json"]))
            elif item.get("url"):
                with urllib.request.urlopen(item["url"], timeout=300) as r:
                    with open(p, "wb") as f:
                        f.write(r.read())
            else:
                raise RuntimeError(f"响应无图像数据：{json.dumps(item)[:200]}")
            paths.append(p)
        if not paths:
            raise RuntimeError(f"响应无图像数据：{json.dumps(data)[:300]}")
        return paths

    def info(self) -> ProviderInfo:
        if not self.api_key:
            return ProviderInfo(self.name, False, "未设置 IMAGE_API_KEY")
        return ProviderInfo(self.name, True,
                            f"{self.base_url} · {self.model}（参考图 → /images/edits）")


class StabilityProvider(ImageProvider):
    name = "stability"

    def __init__(self, cfg: dict | None = None):
        super().__init__(cfg)
        self.api_key = self.cfg.get("api_key") or os.getenv("IMAGE_API_KEY") or ""
        self.base_url = (self.cfg.get("base_url") or "https://api.stability.ai").rstrip("/")
        self.model = self.cfg.get("model") or "core"

    def generate(self, *, prompt: str, negative_prompt: str = "",
                 width: int = 1024, height: int = 1024,
                 out_path: str = "", n: int = 1,
                 reference: str | None = None) -> list[str]:
        if not self.api_key:
            raise RuntimeError("缺少 API Key：请设置环境变量 IMAGE_API_KEY")
        try:
            import requests
        except ImportError as e:
            raise RuntimeError("需要 requests：pip install requests") from e
        ref, prob = resolve_reference(reference)
        if prob:
            raise FileNotFoundError(prob)

        data = {"prompt": prompt, "negative_prompt": negative_prompt,
                "aspect_ratio": _closest_aspect(width, height),
                "output_format": "png"}
        if ref:
            # ⭐ 图生图：Stability 的 `mode=image-to-image` 需**同时**给 image 文件与 strength。
            #    strength 越低越贴原图（生图端不像提示词端，无法"追加一句话"就保持一致）。
            data["mode"] = "image-to-image"
            data["strength"] = str(self.cfg.get("strength", 0.55))
            with open(ref, "rb") as fh:
                files = {"image": (os.path.basename(ref), fh.read(), "image/png")}
        else:
            files = {"none": ""}          # Stability 约定：纯文字生成时占位

        paths = []
        for i in range(max(1, n)):
            p = out_path if n == 1 else f"{os.path.splitext(out_path)[0]}_{i + 1}.png"
            os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
            resp = requests.post(
                f"{self.base_url}/v2beta/stable-image/generate/{self.model}",
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Accept": "image/*"},
                files=files,
                data=data,
                timeout=self.cfg.get("timeout", 300))
            resp.raise_for_status()
            with open(p, "wb") as f:
                f.write(resp.content)
            paths.append(p)
        return paths

    def info(self) -> ProviderInfo:
        if not self.api_key:
            return ProviderInfo(self.name, False, "未设置 IMAGE_API_KEY")
        return ProviderInfo(self.name, True,
                            f"{self.base_url} · {self.model}"
                            f"（参考图 → mode=image-to-image，"
                            f"strength={self.cfg.get('strength', 0.55)}）")


def _closest_aspect(w: int, h: int) -> str:
    choices = {"16:9": 16 / 9, "1:1": 1.0, "3:2": 1.5, "9:16": 9 / 16, "2:3": 2 / 3}
    target = w / h if h else 1
    return min(choices, key=lambda k: abs(choices[k] - target))


# ── ComfyUI（本机后端）────────────────────────────────────────
#
# 注入点**靠连线识别，不靠节点 id 或位置** —— 工作流是用户在 ComfyUI 里画的，
# 节点号随时会变；但 "KSampler.positive 连到哪个 CLIPTextEncode" 是**语义**，
# 换谁重画都得连通才能跑。所以定位一律沿连线走。

_CLIP_TEXT = "CLIPTextEncode"
_SAMPLER_TYPES = ("KSampler", "KSamplerAdvanced")
# 尺寸节点：ComfyUI 里造空 latent 的一族，名字都带 Empty
_LATENT_TYPES = ("EmptySD3LatentImage", "EmptyLatentImage",
                 "EmptyLatentImagePresets", "EmptyLatentImageSDXL")
# 不参与执行、但要留在图里给人看的节点
_SKIP_TYPES = ("Note", "MarkdownNote", "Reroute", "PrimitiveNode")


def graph_to_api(graph: dict) -> dict:
    """节点式工作流（ComfyUI 前端另存）→ API 式（`/prompt` 只吃这种）。

    ⚠️ 映射规则不是猜的，是**对着本机工作流实测出来的**：
       · `node.inputs` 里**没有 `link`** 的项 = widget，按出现顺序取 `widgets_values[i]`；
       · 有 `link` 的项 → 查 links 表还原成 `[上游节点id, 上游输出槽]`；
       · 所有节点 id 在 API 式里必须是**字符串**。
    实测对上：`01_角色定妆板_Qwen2512.json` 的 UNETLoader 2 个 widget ↔ 2 个无 link 输入、
    LoraLoaderModelOnly 2↔2、KSampler 6↔6，逐项一一对应。
    """
    links = {l[0]: l for l in (graph.get("links") or []) if l}
    api: dict[str, dict] = {}
    for node in graph.get("nodes") or []:
        t = node.get("type")
        if not t or t in _SKIP_TYPES or node.get("mode") == 4:   # mode 4 = 前端"旁路"
            continue
        inputs: dict = {}
        wv = node.get("widgets_values") or []
        wi = 0
        for inp in node.get("inputs") or []:
            name = inp.get("name")
            link = inp.get("link")
            if link is not None:
                l = links.get(link)
                if l:
                    inputs[name] = [str(l[1]), l[2]]
            else:
                if wi < len(wv):
                    inputs[name] = wv[wi]
                wi += 1
        api[str(node.get("id"))] = {"class_type": t, "inputs": inputs}
    return api


def _upstream(api: dict, node_id: str, input_name: str) -> str:
    """沿 `node_id.input_name` 的连线找上游节点 id（没连返回空串）。"""
    v = (api.get(node_id) or {}).get("inputs", {}).get(input_name)
    if isinstance(v, list) and v:
        return str(v[0])
    return ""


class ComfyUIProvider(ImageProvider):
    """驱动**本机 ComfyUI** 出图（蓝图 §二十二「由 Provider 决定具体 API」的第四个实现）。

    与 openai / stability 的**根本差异**：那两个是"给文字、还你图"的黑盒；
    ComfyUI 要你**自带一张工作流节点图** —— 本 Provider 只注入四处变量
    （正向词 / 负向词 / 尺寸 / seed），其余节点（模型 / LoRA / VAE / 采样器）
    **一律照工作流原样**。理由：用哪个模型是"配方"，不该由提示词引擎决定 ——
    换配方就换工作流文件，代码一行不动。

    ⚠️ seed 策略：**同一提示词 → 同一 seed**（对 prompt+negative 做哈希派生）。
    这不是随手定的 —— 工作流《ComfyUI 出图流程》§五 把「固定 seed」列为一致性的第 1 条。
    cfg 里显式给 `seed` 则覆盖它（想做多张变化时用）。

    ⚠️ 参考图（reference）：**只在工作流里有 LoadImage 节点时**支持；
    没有就**直接报错**，绝不静默降级成纯文字生成 —— 工作流 §4.1 的警告正是
    「各角度独立从文字生成 → 空间必然漂移」。
    """

    name = "comfyui"

    def __init__(self, cfg: dict | None = None):
        super().__init__(cfg)
        sub = self.cfg.get("comfyui") or {}
        self.base_url = (sub.get("base_url") or self.cfg.get("base_url")
                         or os.getenv("COMFYUI_BASE_URL")
                         or "http://127.0.0.1:8188").rstrip("/")
        self.workflow_path = sub.get("workflow") or os.getenv("COMFYUI_WORKFLOW") or ""
        self.timeout = int(sub.get("timeout") or self.cfg.get("timeout") or 600)
        self.poll = float(sub.get("poll") or 1.5)
        self.filename_prefix = sub.get("filename_prefix") or ""
        self.seed_override = sub.get("seed")
        self.overrides: dict = sub.get("overrides") or {}

    # ── 网络原语（纯标准库）──

    def _get(self, path: str, *, timeout: float = 15) -> bytes:
        with urllib.request.urlopen(f"{self.base_url}{path}", timeout=timeout) as r:
            return r.read()

    def _post_json(self, path: str, payload: dict, *, timeout: float = 30) -> dict:
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def _upload_image(self, path: str) -> str:
        """把参考图 POST 到 `/upload/image`，返回 ComfyUI 侧的文件名。"""
        import uuid  # noqa: PLC0415  （仅参考图路径用到）
        boundary = "----manju" + uuid.uuid4().hex
        name = os.path.basename(path)
        with open(path, "rb") as f:
            blob = f.read()
        body = b"".join([
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="image"; filename="'
            + name.encode("utf-8") + b'"\r\n',
            b"Content-Type: image/png\r\n\r\n", blob, b"\r\n",
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n',
            f"--{boundary}--\r\n".encode(),
        ])
        req = urllib.request.Request(
            f"{self.base_url}/upload/image", data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.loads(r.read().decode("utf-8"))
        sub = res.get("subfolder") or ""
        return f"{sub}/{res['name']}" if sub else res["name"]

    def info(self) -> ProviderInfo:
        if not self.workflow_path:
            return ProviderInfo(self.name, False,
                                "未配置工作流：`image.comfyui.workflow` 或 COMFYUI_WORKFLOW",
                                needs_key=False)
        if not os.path.isfile(self.workflow_path):
            return ProviderInfo(self.name, False,
                                f"工作流文件不存在：{self.workflow_path}", needs_key=False)
        try:
            st = json.loads(self._get("/system_stats", timeout=5))
            ver = (st.get("system") or {}).get("comfyui_version", "?")
            return ProviderInfo(
                self.name, True,
                f"{self.base_url} · ComfyUI {ver} · 工作流 "
                f"{os.path.basename(self.workflow_path)}", needs_key=False)
        except Exception as e:                                     # noqa: BLE001
            return ProviderInfo(self.name, False,
                                f"连不上 {self.base_url}（{type(e).__name__}）"
                                f" —— ComfyUI 没启动？", needs_key=False)

    # ── 生成 ──

    def _seed_for(self, prompt: str, negative_prompt: str, i: int) -> int:
        if self.seed_override is not None:
            base = int(self.seed_override)
        else:
            d = hashlib.sha256((prompt + "\x00" + negative_prompt).encode("utf-8")).digest()
            base = int.from_bytes(d[:6], "big") & 0x7FFF_FFFF
        return (base + i) & 0x7FFF_FFFF

    def _plan(self, api: dict) -> dict:
        """定位四个注入点；任一定位不到就**明确报错**，不猜、不降级。"""
        sid = next((i for i, n in api.items() if n["class_type"] in _SAMPLER_TYPES), None)
        if not sid:
            raise RuntimeError(
                f"工作流里找不到采样器（{'/'.join(_SAMPLER_TYPES)}）：{self.workflow_path}")
        pos = _upstream(api, sid, "positive")
        neg = _upstream(api, sid, "negative")
        lat = _upstream(api, sid, "latent_image")
        if not pos or api[pos]["class_type"] != _CLIP_TEXT:
            raise RuntimeError(
                f"KSampler.positive 没连到 CLIPTextEncode（实际："
                f"{api.get(pos, {}).get('class_type') or '未连线'}）—— 无法注入正向提示词。"
                f"工作流：{self.workflow_path}")
        if not neg or api[neg]["class_type"] != _CLIP_TEXT:
            raise RuntimeError(
                f"KSampler.negative 没连到 CLIPTextEncode（实际："
                f"{api.get(neg, {}).get('class_type') or '未连线'}）—— 无法注入负向提示词。"
                f"工作流：{self.workflow_path}")
        if lat and api[lat]["class_type"] not in _LATENT_TYPES:
            lat = ""                    # 尺寸由上游图像决定（图生图）→ 不改尺寸，如实放着
        return {"sampler": sid, "pos": pos, "neg": neg, "latent": lat}

    def _run_one(self, job: dict, out_path: str, want: tuple[int, int]) -> None:
        res = self._post_json("/prompt", {"prompt": job})
        pid = res.get("prompt_id")
        if not pid:
            raise RuntimeError(
                f"ComfyUI 未返回 prompt_id（多半是工作流校验没过）："
                f"{json.dumps(res, ensure_ascii=False)[:400]}")

        entry, deadline = None, time.time() + self.timeout
        while time.time() < deadline:
            hist = json.loads(self._get(f"/history/{pid}"))
            entry = hist.get(pid)
            if entry:
                st = entry.get("status") or {}
                if st.get("status_str") == "error":
                    msgs = [m for m in (st.get("messages") or []) if "error" in str(m).lower()]
                    raise RuntimeError(
                        f"ComfyUI 执行报错：{json.dumps(msgs or st, ensure_ascii=False)[:500]}")
                if entry.get("outputs"):
                    break
            time.sleep(self.poll)
        else:
            raise TimeoutError(
                f"等 ComfyUI 出图超时（{self.timeout}s，prompt_id={pid}）。"
                f"大模型首次加载要算进这个时间，可在 `image.comfyui.timeout` 调大。")

        images: list[dict] = []
        for node_out in (entry.get("outputs") or {}).values():
            images.extend(node_out.get("images") or [])
        if not images:
            raise RuntimeError(
                "ComfyUI 跑完了但没有任何图像输出 —— 工作流里是不是没有 SaveImage / PreviewImage？")

        im = images[0]
        q = urllib.parse.urlencode({"filename": im["filename"],
                                    "subfolder": im.get("subfolder", ""),
                                    "type": im.get("type", "output")})
        blob = self._get(f"/view?{q}", timeout=max(120.0, self.timeout / 2))
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(blob)

        w, h = png_size(out_path)
        if (w, h) != (None, None) and (w, h) != want:
            # 尺寸对不上 = 注入没生效（或工作流下游另改了尺寸）。宁可炸，
            # 也不要交出一张"看着出来了、其实规格错了"的图 —— 工作流《出图流程》§八 的排错项。
            raise RuntimeError(
                f"产出尺寸 {w}x{h} 与请求 {want[0]}x{want[1]} 不符 —— "
                f"尺寸注入没生效，请检查工作流里 KSampler.latent_image 上游那个 latent 节点。")

    def generate(self, *, prompt: str, negative_prompt: str = "",
                 width: int = 1024, height: int = 1024,
                 out_path: str = "", n: int = 1,
                 reference: str | None = None) -> list[str]:
        if not self.workflow_path or not os.path.isfile(self.workflow_path):
            raise RuntimeError(
                "未配置 ComfyUI 工作流：请在 `image.comfyui.workflow` 指定一张节点式工作流 JSON"
                f"（实际：{self.workflow_path or '空'}）")
        ref, prob = resolve_reference(reference)
        if prob:
            raise FileNotFoundError(prob)

        with open(self.workflow_path, encoding="utf-8") as f:
            graph = json.load(f)
        api = graph_to_api(graph)
        if not api:
            raise RuntimeError(f"工作流解析后为空（不是节点式 JSON？）：{self.workflow_path}")
        plan = self._plan(api)

        if ref:
            load = next((i for i, nd in api.items() if nd["class_type"] == "LoadImage"), None)
            if not load:
                raise RuntimeError(
                    f"传了参考图，但工作流里没有 LoadImage 节点："
                    f"{os.path.basename(self.workflow_path)} —— 拒绝静默降级为纯文字生成"
                    f"（工作流 §4.1：各角度独立从文字生成，空间必然漂移）")
            api[load]["inputs"]["image"] = self._upload_image(ref)

        want = (int(width), int(height))
        paths: list[str] = []
        for i in range(max(1, n)):
            job = copy.deepcopy(api)
            job[plan["pos"]]["inputs"]["text"] = prompt
            job[plan["neg"]]["inputs"]["text"] = negative_prompt or ""
            if plan["latent"]:
                job[plan["latent"]]["inputs"]["width"] = want[0]
                job[plan["latent"]]["inputs"]["height"] = want[1]
                job[plan["latent"]]["inputs"].setdefault("batch_size", 1)
            job[plan["sampler"]]["inputs"]["seed"] = self._seed_for(prompt, negative_prompt, i)
            for nid, patch in self.overrides.items():          # 逃生口：按节点 id 覆盖任意输入
                if nid in job:
                    job[nid]["inputs"].update(patch)
            if self.filename_prefix:
                for nd in job.values():
                    if nd["class_type"] == "SaveImage":
                        nd["inputs"]["filename_prefix"] = self.filename_prefix

            p = out_path if n == 1 else f"{os.path.splitext(out_path)[0]}_{i + 1}.png"
            self._run_one(job, p, want)
            paths.append(p)
        return paths


PROVIDERS: dict[str, type[ImageProvider]] = {
    "mock": MockProvider, "openai": OpenAICompatProvider,
    "stability": StabilityProvider, "comfyui": ComfyUIProvider,
}


def get_provider(name: str, cfg: dict | None = None) -> ImageProvider:
    if name not in PROVIDERS:
        raise ValueError(f"未知 provider：{name}（可选 {list(PROVIDERS)}）")
    return PROVIDERS[name](cfg)


def list_providers(cfg: dict | None = None) -> list[ProviderInfo]:
    return [cls(cfg).info() for cls in PROVIDERS.values()]
