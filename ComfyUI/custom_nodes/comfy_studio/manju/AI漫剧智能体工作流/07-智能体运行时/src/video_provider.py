"""出视频 Provider —— 把「分镜 + 首帧/尾帧图」交给本机 ComfyUI 的 MiniMax H3 出片。

与 `image_provider` 同一台 ComfyUI、同一套网络原语（`comfy_http`），但注入方式不同，
所以单独一份：出图注入的是正/负提示词与尺寸，出视频要注入的是 **Director 节点**的
`timeline_data`（整条时间线的 JSON 字符串）+ 尺寸/帧率/总帧数/seed。

⚠️ 这个节点的 widget **不能用位置映射**（实测）：`MiniMaxH3Director` 存了 21 个
widget 值，而节点声明里只有 20 个 widget（多的是前端 JS 侧控件，值 `"fixed"`），
位置映射从 `frame_rate` 起全体后移一位（`frame_rate="fixed"`、`timeline_data=124`）。
这种错法不报错、照样出片，只是参数全错 —— 所以这里按**名字**对齐
（`align_widgets`，向运行中的 ComfyUI 要 `/object_info` 的声明顺序）。

时间线 schema（`director/fl2v_timeline.py` 的权威说明）：`timeline.shots[]` 每镜一组，
含 `startImage`（首帧，可空）/ `endImage`（尾帧，可空，FL2VA 允许只给尾帧）/
`durationSec` / `prompt` / `negativePrompt`；`imageFile` 是**相对 ComfyUI input/
目录**的路径，所以首尾帧要先上传。空 shots（纯文生视频）也合法。

时长换算（官方公式）：`frames = max(5, round(秒 × 帧率))` 再补到 17k+5，
所以 5.0s@24fps → 124 帧 = 5.17s。这里照抄公式**只为核对**产物时长，不改写。

一次跑整条 vs 逐镜跑：默认逐镜（`batch=false`）。整条连贯性更好，但一镜坏整段白跑、
长任务易超时；逐镜可续跑、可单镜重出，接缝靠"每镜首帧来自同一套资产图"保人物一致。
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from .comfy_http import (http_get, object_info, post_json, system_stats,
                         upload_image, view_blob)
from .film import FfmpegError, ffmpeg_bin, ffprobe_meta, have_ffmpeg
from .image_provider import ProviderInfo, graph_to_api

__all__ = ["AlignReport", "ComfyUIVideoProvider", "MockVideoProvider", "Shot",
           "VideoProvider", "align_widgets", "auto_workflow", "build_timeline",
           "collect_video_ref", "declared_widgets", "find_comfy_root",
           "get_video_provider", "list_video_providers", "minimax_frames"]


class VideoProvider(ABC):
    """视频 Provider 的统一接口 —— 与 `image_provider.ImageProvider` 对位。

    `render` 吃的是**分镜**（`Shot` 列表）而不是单条提示词：出片天然是"多镜成片"，
    接口按这个来，流水线就不用自己攒循环。
    """

    name = "base"

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or {}

    @abstractmethod
    def render(self, shots: list["Shot"], *, out_dir: str,
               force: bool = False) -> list[str]:
        """出片，返回产物路径（顺序与 shots 一致）。"""

    @abstractmethod
    def info(self) -> ProviderInfo:
        """能不能用、为什么不能用（`doctor` 直接印这个）。"""

# 这些声明类型是"插槽"（连线用），不是 widget；对不上号时不能算进 widget 序列。
SOCKET_TYPES = frozenset({
    "MODEL", "CLIP", "VAE", "IMAGE", "MASK", "LATENT", "SIGMAS", "CONDITIONING",
    "AUDIO", "VIDEO", "CONTROL_NET", "UPSCALE_MODEL", "STYLE_MODEL", "CLIP_VISION",
})

VIDEO_EXTS = (".mp4", ".webm", ".mov", ".mkv", ".gif")
DEFAULT_WORKFLOW_GLOBS = (
    "user/default/workflows/AIGC中国风漫剧/*视频*fl2v*.json",
    "user/default/workflows/**/*fl2v*.json",
    "user/default/workflows/**/*视频*.json",
)


def minimax_frames(seconds: float, fps: float = 24.0) -> int:
    """官方换算：`max(5, round(秒 × fps))` 再补到 17k+5。"""
    a = max(0.1, float(seconds or 0.1))
    rate = max(1.0, float(fps or 24.0))
    n = max(5, int(round(a * rate)))
    return n + (5 - (n % 17)) % 17


@dataclass
class Shot:
    """一个镜头要出的那一段视频。"""
    id: str = "S01"
    prompt: str = ""
    seconds: float = 5.0
    first_frame: str = ""          # 本地 PNG 路径（上传后成为 startImage）
    last_frame: str = ""           # 本地 PNG 路径（可选）
    negative: str = ""
    seed: int | None = None
    note: str = ""                 # 分镜表里的景别/机位等，只用于日志

    def frames(self, fps: float) -> int:
        return minimax_frames(self.seconds, fps)


@dataclass
class AlignReport:
    """`widgets_values` → 按名字的映射结果 + 对齐过程中的异常说明。"""
    mapping: dict = field(default_factory=dict)
    used_default: list = field(default_factory=list)   # 没找到对应值 → 用声明默认值
    stray: list = field(default_factory=list)          # 没有输入对应的多余值（JS 控件）
    shifted: bool = False                              # 是否发生了"整体错位"

    def describe(self, declared: set | None = None) -> list[str]:
        """`declared` = 这张图里前端真正会发的输入名（给了就只报这些）。"""
        out = []
        if self.shifted:
            out.append(f"widget 与声明对不齐：多出 {len(self.stray)} 个无名值 "
                       f"{[v for _, v in self.stray]} —— 已按**名字**对齐，未按位置")
        miss = [nm for nm in self.used_default if declared is None or nm in declared]
        if miss:
            out.append(f"这些输入没值可取，已回落到节点声明默认值：{miss}")
        return out


def declared_widgets(info: dict) -> tuple[list[str], list]:
    """从 `/object_info/<节点>` 结果里取「能当 widget 的输入」：名字 + 声明类型。

    顺序 = 声明顺序 = 前端 `widgets_values` 的顺序（除开前端 JS 自己加的那些）。
    ⚠️ 新版 ComfyUI 的 `/object_info` **不再返回 `input.order`**（实测 0.37 是这样），
    顺序只体现在 `required` / `optional` 两个 dict 的**插入顺序**里 —— 所以这里
    先认 `order`（老版），没有再退回 dict 的键序。
    """
    inp = info.get("input") or {}
    order = info.get("input_order") or inp.get("order") or {}
    names: list[str] = []
    specs: list = []
    for sect in ("required", "optional"):
        seq = order.get(sect) if isinstance(order.get(sect), list) else None
        if seq is None:
            seq = list((inp.get(sect) or {}).keys())
        for nm in seq:
            spec = (inp.get(sect) or {}).get(nm)
            if not isinstance(spec, list) or not spec:
                continue
            t = spec[0]
            if isinstance(t, str) and t in SOCKET_TYPES:
                continue
            names.append(nm)
            specs.append(t)          # 列表 = COMBO（枚举）；字符串 = 类型名
    return names, specs


def _compat(spec, v) -> int:
    """值 v 像不像这个声明？0 = 不可能（一定不是它）；1 = 勉强；2 = 就是它。"""
    t = "COMBO" if isinstance(spec, list) else str(spec).upper()
    if t == "BOOLEAN":
        return 2 if isinstance(v, bool) else 0
    if isinstance(v, bool):                       # bool 是 int 的子类，先挡掉
        return 0
    if t == "FLOAT":
        return 2 if isinstance(v, (int, float)) else 0
    if t == "INT":
        if isinstance(v, int):
            return 2
        return 1 if isinstance(v, float) and float(v).is_integer() else 0
    if t == "STRING":
        return 2 if isinstance(v, str) else 0
    if t == "COMBO":
        if not isinstance(v, str):
            return 0
        return 2 if (not spec or v in spec) else 1   # 动态下拉常不在静态列表里
    return 0


def align_widgets(names: list[str], specs: list, values: list,
                  defaults: dict | None = None) -> AlignReport:
    """把位置存储的 `widgets_values` 按**名字**对齐成 dict。

    做法：先给 (名字, 值) 打"像不像"分，再跑一遍**保序最大匹配**（分高者优先，
    同分取偏移最小那组），剩下的名字用声明默认值补。这样前端多塞一个 JS 控件
    （整体后移一位）也能自动纠回来。
    """
    defaults = defaults or {}
    n, m = len(names), len(values)
    dp: list[list[tuple[int, int]]] = [[(0, 0)] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            best = dp[i - 1][j] if dp[i - 1][j] >= dp[i][j - 1] else dp[i][j - 1]
            w = _compat(specs[i - 1], values[j - 1])
            if w:
                s0, c0 = dp[i - 1][j - 1]
                cand = (s0 + w, c0 + abs((i - 1) - (j - 1)))
                if cand[0] > best[0] or (cand[0] == best[0] and cand[1] < best[1]):
                    best = cand
            dp[i][j] = best

    pairs: list[tuple[int, int]] = []
    i, j = n, m
    while i > 0 and j > 0:
        if dp[i][j] == dp[i - 1][j]:
            i -= 1
        elif dp[i][j] == dp[i][j - 1]:
            j -= 1
        else:
            pairs.append((i - 1, j - 1))
            i -= 1
            j -= 1
    pairs.reverse()
    matched_i = {a for a, _ in pairs}
    matched_j = {b for _, b in pairs}
    rep = AlignReport(mapping={names[a]: values[b] for a, b in pairs})
    rep.stray = [(k, values[k]) for k in range(m) if k not in matched_j]
    rep.used_default = [nm for k, nm in enumerate(names) if k not in matched_i]
    rep.shifted = any(b - a for a, b in pairs)
    for nm in rep.used_default:
        if nm in defaults:
            rep.mapping[nm] = defaults[nm]
    return rep


def build_timeline(template: dict, shots: list[Shot], *, fps: float,
                   width: int, height: int, global_prompt: str = "") -> dict:
    """用**工作流里那张跑通过的时间线**当模板，只替换需要改的字段。

    为什么不从零拼一份 schema：时间线字段几十个（`output`/`global`/`refAudios`…），
    从零拼等于替上游猜结构，猜错了是"跑得过、效果不对"；拿模板改字段，
    结构永远是上游认得的那个。
    """
    tl = copy.deepcopy(template)
    rows = []
    for s in shots:
        row: dict = {"id": s.id, "prompt": s.prompt.strip(), "durationSec": float(s.seconds)}
        if s.negative:
            row["negativePrompt"] = s.negative
        if s.first_frame:
            row["startImage"] = {"imageFile": s.first_frame, "imageB64": ""}
        if s.last_frame:
            row["endImage"] = {"imageFile": s.last_frame, "imageB64": ""}
        rows.append(row)

    tl["frameRate"] = float(fps)
    tl["totalFrames"] = int(sum(s.frames(fps) for s in shots))
    tl["shots"] = rows
    tl["timelineMode"] = "fl2v"
    tl.pop("segments", None)      # 老 schema 与 shots 不能同时在，留着会看错源
    tl.pop("keyframes", None)
    g = tl.get("global")
    tl["global"] = {**(g if isinstance(g, dict) else {}), "prompt": global_prompt or ""}
    o = tl.get("output")
    tl["output"] = {**(o if isinstance(o, dict) else {}), "mode": "fixed",
                    "width": int(width), "height": int(height),
                    "longEdge": max(int(width), int(height))}
    return tl


def collect_video_ref(outputs: dict) -> dict | None:
    """从 `/history` 的 outputs 里挑出视频产物（mp4/webm/mov），mp4 优先。"""
    cands: list[dict] = []
    for node_out in (outputs or {}).values():
        for key in ("gifs", "videos", "images", "audio"):
            for it in node_out.get(key) or []:
                if isinstance(it, dict) and str(it.get("filename", "")).lower().endswith(VIDEO_EXTS):
                    cands.append(it)
    if not cands:
        return None
    cands.sort(key=lambda it: (not str(it["filename"]).lower().endswith(".mp4"),))
    return cands[0]


def find_comfy_root(start=None) -> str:
    """找 ComfyUI 根目录：`COMFYUI_ROOT` → 从本文件往上找 `user/default/workflows`。"""
    env = os.getenv("COMFYUI_ROOT")
    if env and os.path.isdir(env):
        return os.path.abspath(env)
    p = Path(start or __file__).resolve()
    for up in (p, *p.parents):
        if (up / "user" / "default" / "workflows").is_dir():
            return str(up)
        if (up / "main.py").is_file() and (up / "comfy").is_dir():
            return str(up)
    return ""


def auto_workflow(glob_pat: str = "") -> str:
    """照着 ComfyUI 的 workflows 目录找一张视频工作流（找不到返回空串）。"""
    root = find_comfy_root()
    if not root:
        return ""
    for pat in ((glob_pat,) if glob_pat else DEFAULT_WORKFLOW_GLOBS):
        hits = sorted(Path(root).glob(pat))
        if hits:
            hits.sort(key=lambda p: (0 if "试片" in p.name else 1, len(p.name)))
            return str(hits[0])
    return ""


def _timeline_template(node: dict | None, director_type: str) -> dict:
    """拿 Director 节点里存着的那段时间线当模板（`timeline_data` 是 JSON 字符串）。"""
    if not node:
        raise RuntimeError(f"工作流里没有 {director_type} 节点")
    wv = node.get("widgets_values") or []
    for v in wv:
        if isinstance(v, str) and v.strip().startswith("{"):
            try:
                tl = json.loads(v)
            except json.JSONDecodeError:
                continue
            if isinstance(tl, dict) and ("version" in tl or "timelineMode" in tl
                                        or "totalFrames" in tl):
                return tl
    raise RuntimeError(
        f"{director_type} 节点的 widgets_values 里找不到可解析的时间线模板 —— "
        f"先用 ComfyUI 界面把这张工作流存一次（带 timeline_data）再跑")


def _verify_clip(path: str, *, expect_frames: int, fps: float,
                 want: tuple[int, int]) -> dict:
    """回读产物：是不是真视频、时长/尺寸对不对。对不上就炸，不静默放过。"""
    if not os.path.isfile(path) or os.path.getsize(path) < 1024:
        raise RuntimeError(f"产物空的或没落盘：{path}")
    with open(path, "rb") as f:
        head = f.read(12)
    if len(head) < 12 or head[4:8] not in (b"ftyp", b"moov", b"webm"):
        raise RuntimeError(f"产物不像视频（文件头 {head[:8]!r}）：{path}")
    if not have_ffmpeg():
        return {"path": path, "width": 0, "height": 0, "duration": 0.0,
                "has_audio": False, "nb_frames": 0,
                "note": "没装 ffmpeg，跳过时长/尺寸核对"}
    meta = ffprobe_meta(path)
    expect_sec = expect_frames / max(1.0, fps)
    if abs(meta["duration"] - expect_sec) > max(1.0, 0.25 * expect_sec):
        print(f"⚠️  {os.path.basename(path)} 时长 {meta['duration']:.2f}s 与预期 "
              f"{expect_sec:.2f}s（{expect_frames} 帧）差得多 —— 检查 total_frames/durationSec")
    if want[0] and (meta["width"], meta["height"]) != tuple(want):
        print(f"⚠️  {os.path.basename(path)} 分辨率 {meta['width']}×{meta['height']} "
              f"与配置 {want[0]}×{want[1]} 不一致")
    return meta


class ComfyUIVideoProvider(VideoProvider):
    """驱动本机 ComfyUI 的 MiniMax H3 Director 出片（默认逐镜一张 job）。"""

    name = "comfyui"

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or {}
        sub = self.cfg.get("comfyui") or {}
        self.base_url = (sub.get("base_url") or os.getenv("COMFYUI_URL")
                         or "http://127.0.0.1:8188").rstrip("/")
        self.workflow_path = (sub.get("workflow") or os.getenv("COMFYUI_VIDEO_WORKFLOW")
                              or auto_workflow(sub.get("workflow_glob") or ""))
        self.width = int(sub.get("width") or self.cfg.get("width") or 1344)
        self.height = int(sub.get("height") or self.cfg.get("height") or 768)
        self.fps = float(sub.get("fps") or self.cfg.get("fps") or 24)
        self.timeout = float(sub.get("timeout") or 5400)     # 首次加载大模型要算进来
        self.poll = float(sub.get("poll") or 3)
        self.batch = bool(sub.get("batch") or False)
        self.filename_prefix = sub.get("filename_prefix") or ""
        self.director_node = sub.get("director_node") or "MiniMaxH3Director"
        self.global_prompt = (sub.get("global_prompt") or self.cfg.get("global_prompt")
                              or self.cfg.get("prompt") or "")
        self.seed_override = sub.get("seed")
        self.overrides = sub.get("overrides") or {}
        self.quiet = bool(sub.get("quiet") or self.cfg.get("quiet"))
        self._info_cache: dict = {}

    def _say(self, msg: str) -> None:
        if not self.quiet:
            print(msg, flush=True)

    def info(self) -> ProviderInfo:
        if not self.workflow_path:
            return ProviderInfo(self.name, False,
                                "未配置视频工作流：`video.comfyui.workflow` 或 "
                                "COMFYUI_VIDEO_WORKFLOW（也可放一张 fl2v 工作流到 ComfyUI 的 workflows 目录）",
                                needs_key=False)
        if not os.path.isfile(self.workflow_path):
            return ProviderInfo(self.name, False,
                                f"视频工作流文件不存在：{self.workflow_path}", needs_key=False)
        try:
            st = system_stats(self.base_url, timeout=5)
            ver = (st.get("system") or {}).get("comfyui_version", "?")
            return ProviderInfo(
                self.name, True,
                f"{self.base_url} · ComfyUI {ver} · {self.width}×{self.height}@{self.fps:g}fps · "
                f"工作流 {os.path.basename(self.workflow_path)}"
                + ("（整条时间线一次跑）" if self.batch else "（逐镜跑）"),
                needs_key=False)
        except Exception as e:                                        # noqa: BLE001
            return ProviderInfo(self.name, False,
                                f"连不上 {self.base_url}（{type(e).__name__}）—— ComfyUI 没启动？",
                                needs_key=False)

    def node_info(self, class_type: str) -> dict:
        if class_type not in self._info_cache:
            self._info_cache[class_type] = object_info(self.base_url, class_type)
        return self._info_cache[class_type]

    def _load(self) -> tuple[dict, dict, dict, dict]:
        """读工作流 → 转 API 格式 → 拿到 Director 的**原始** widget 值与它声明的输入名。"""
        with open(self.workflow_path, encoding="utf-8") as f:
            graph = json.load(f)
        if "nodes" not in graph:
            raise RuntimeError(f"这不是节点式工作流（前端另存的那种）JSON：{self.workflow_path}")
        api = graph_to_api(graph)
        if not api:
            raise RuntimeError(f"工作流解析后为空：{self.workflow_path}")
        raw = {str(n.get("id")): (n.get("widgets_values") or []) for n in graph["nodes"]}
        node = next((n for n in graph["nodes"] if n.get("type") == self.director_node), None)
        # 前端在这张图里真正会发的输入名：只往这些名字里注入，
        # 免得把 `i2v_groups` 这类"声明里有、这张图没渲染"的可选项硬塞给 /prompt。
        wired = {i.get("name") for i in (node or {}).get("inputs", []) if i.get("name")}
        return api, raw, _timeline_template(node, self.director_node), wired

    def _patch_director(self, job: dict, shots: list[Shot], *, seed: int,
                        template: dict, raw: dict, wired: set | None = None) -> list[str]:
        """按名字改 Director 节点的参数，返回需要打印的对齐说明。"""
        nid = next((i for i, nd in job.items() if nd["class_type"] == self.director_node), None)
        if not nid:
            raise RuntimeError(f"视频工作流里找不到 {self.director_node} 节点："
                               f"{self.workflow_path}（这张图不是 Director 出片的？）")
        values = raw.get(nid)
        if values is None:
            raise RuntimeError(f"定位不到节点 #{nid} 的 widgets_values —— 拒绝继续猜")
        info = self.node_info(self.director_node)
        names, specs = declared_widgets(info)
        if not names:
            raise RuntimeError(f"取不到 {self.director_node} 的输入声明（/object_info 为空）"
                               f"—— 确认 ComfyUI 里这个自定义节点已加载")
        req = info.get("input", {}).get("required", {})
        opt = info.get("input", {}).get("optional", {})
        defaults = {}
        for nm in names:
            spec = req.get(nm) or opt.get(nm) or [None, {}]
            defaults[nm] = (spec[1] or {}).get("default") if len(spec) > 1 else None
        rep = align_widgets(names, specs, values, defaults)

        tl = build_timeline(template, shots, fps=self.fps, width=self.width,
                            height=self.height, global_prompt=self.global_prompt)
        patch = dict(rep.mapping)
        # 这几个字段由我们说了算：对齐结果只用来确认字段名存在，值一律覆盖。
        patch.update({"timeline_data": json.dumps(tl, ensure_ascii=False),
                      "frame_rate": self.fps, "width": self.width, "height": self.height,
                      "total_frames": int(tl["totalFrames"]), "seed": int(seed)})
        if self.global_prompt:
            patch["global_prompt"] = self.global_prompt
        allow = wired or set()
        for k, v in patch.items():
            if v is None:
                continue                       # 声明里没有默认值的（如必填字符串）别塞 None
            if allow and k not in allow:
                continue                       # 声明有、但这张图前端没渲染的可选项：不注入
            job[nid]["inputs"][k] = v
        for nid2, extra in (self.overrides or {}).items():
            if nid2 in job:
                job[nid2]["inputs"].update(extra)

        # 自检：错位那种错"跑得通、参数全错"，必须当场认出来。
        if not isinstance(job[nid]["inputs"].get("timeline_data"), str):
            raise RuntimeError(f"timeline_data 注入后不是字符串："
                               f"{job[nid]['inputs'].get('timeline_data')!r} —— widget 对齐失败")
        for chk in ("width", "height", "frame_rate", "total_frames"):
            if not isinstance(job[nid]["inputs"].get(chk), (int, float)):
                raise RuntimeError(f"{chk} 注入后不是数字：{job[nid]['inputs'].get(chk)!r}")
        return rep.describe()

    def _upload(self, path: str, cache: dict) -> str:
        if path not in cache:
            cache[path] = upload_image(self.base_url, path)
        return cache[path]

    def _seed(self, shot: Shot, idx: int) -> int:
        if shot.seed is not None:
            return int(shot.seed)
        if self.seed_override not in (None, ""):
            return int(self.seed_override) + idx
        return int(time.time()) % 2 ** 31 + idx      # 不给 seed 就每镜随机，别让全片一个脸

    def _run_one(self, job: dict, out_path: str, *, expect_frames: int, label: str) -> dict:
        """提交一张 job、等它跑完、把视频取回落盘并核对。"""
        res = post_json(self.base_url, "/prompt", {"prompt": job}, timeout=120)
        pid = res.get("prompt_id")
        if not pid:
            raise RuntimeError("ComfyUI 未返回 prompt_id（工作流校验没过？）："
                               + json.dumps(res, ensure_ascii=False)[:600])
        self._say(f"   已提交 {label}：prompt_id={pid}（{expect_frames} 帧 ≈ "
                  f"{expect_frames / self.fps:.2f}s，等出片…）")

        entry, t0, last = None, time.time(), 0.0
        while time.time() - t0 < self.timeout:
            hist = json.loads(http_get(self.base_url, f"/history/{pid}", timeout=30))
            entry = hist.get(pid)
            if entry:
                st = entry.get("status") or {}
                if st.get("status_str") == "error":
                    errs = [m for m in (st.get("messages") or []) if "error" in str(m).lower()]
                    raise RuntimeError(f"ComfyUI 执行报错（{label}）："
                                       f"{json.dumps(errs or st, ensure_ascii=False)[:800]}")
                if entry.get("outputs"):
                    break
            if time.time() - last > 60:
                last = time.time()
                self._say(f"   … {label} 还在跑（已等 {int(time.time() - t0)}s）")
            time.sleep(self.poll)
        else:
            raise TimeoutError(f"等 ComfyUI 出视频超时（{self.timeout}s，prompt_id={pid}，{label}）。"
                               f"首次加载大模型 + 采样都要算进来，可在 `video.comfyui.timeout` 调大。")

        ref = collect_video_ref(entry.get("outputs") or {})
        if not ref:
            raise RuntimeError(f"ComfyUI 跑完了但没等到视频产物（{label}）—— 工作流里有没有 SaveVideo？"
                               f"outputs={json.dumps(entry.get('outputs'), ensure_ascii=False)[:400]}")
        blob = view_blob(self.base_url, ref, timeout=max(300.0, self.timeout / 4))
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(blob)
        return _verify_clip(out_path, expect_frames=expect_frames, fps=self.fps,
                            want=(self.width, self.height))

    # ── 对外主入口 ──

    def render(self, shots: list[Shot], *, out_dir: str, force: bool = False) -> list[str]:
        """出片，返回产物路径列表（已存在且不 `force` 的镜直接跳过 —— 断点续跑）。"""
        if not self.workflow_path or not os.path.isfile(self.workflow_path):
            raise RuntimeError("未配置视频工作流：请在 `video.comfyui.workflow` 指定 fl2v 工作流 JSON"
                               f"（实际：{self.workflow_path or '空'}）")
        shots = [s for s in shots if s]
        if not shots:
            raise RuntimeError("没有镜头可出：分镜表为空？")
        for s in shots:
            if not s.prompt.strip():
                raise RuntimeError(f"镜 {s.id} 的提示词是空的 —— 拒绝出这种片（多半是分镜没拆好）")
            for fp in (s.first_frame, s.last_frame):
                if fp and not os.path.isfile(fp):
                    raise FileNotFoundError(f"镜 {s.id} 的首/尾帧不存在：{fp}")

        api, raw, tpl, wired = self._load()
        save_nodes = [i for i, nd in api.items()
                      if "SaveVideo" in nd["class_type"] or "VideoCombine" in nd["class_type"]]
        if not save_nodes:
            raise RuntimeError(f"工作流里没有 SaveVideo/VHS_VideoCombine 节点：{self.workflow_path}")
        stem = os.path.basename(out_dir.rstrip("/\\")) or "clip"
        prefix = self.filename_prefix or f"AI漫剧/片段/{stem}"
        up_cache: dict = {}
        paths: list[str] = []

        def _job(sel: list[Shot], seed: int) -> dict:
            j = copy.deepcopy(api)
            # 首尾帧要先上传：imageFile 必须是**相对 ComfyUI input/ 目录**的路径
            prepared = []
            for s in sel:
                one = copy.copy(s)
                if one.first_frame:
                    one.first_frame = self._upload(one.first_frame, up_cache)
                if one.last_frame:
                    one.last_frame = self._upload(one.last_frame, up_cache)
                prepared.append(one)
            notes = self._patch_director(j, prepared, seed=seed, template=tpl,
                                         raw=raw, wired=wired)
            for ln in notes:
                self._say(f"⚠️  {ln}")
            return j

        if self.batch:      # 整条时间线一次跑：连贯性最好，但一镜坏整段白跑
            out_path = os.path.join(out_dir, f"{shots[0].id}_x{len(shots)}.mp4")
            if os.path.isfile(out_path) and not force:
                self._say(f"⏭️  已有整条产物，跳过：{out_path}")
                return [out_path]
            job = _job(shots, self._seed(shots[0], 0))
            for nid in save_nodes:
                job[nid]["inputs"]["filename_prefix"] = prefix
            meta = self._run_one(job, out_path,
                                 expect_frames=sum(s.frames(self.fps) for s in shots),
                                 label=f"整条 {len(shots)} 镜")
            self._say(f"✅ 整条出片 {out_path} · {meta['width']}×{meta['height']} · "
                      f"{meta['duration']:.2f}s · {'带音轨' if meta['has_audio'] else '无音轨'}")
            return [out_path]

        for i, s in enumerate(shots):
            out_path = os.path.join(out_dir, f"{s.id}.mp4")
            if os.path.isfile(out_path) and not force:
                self._say(f"⏭️  镜 {s.id} 已有产物，跳过（要重出加 --重跑）：{out_path}")
                paths.append(out_path)
                continue
            job = _job([s], self._seed(s, i))
            for nid in save_nodes:
                job[nid]["inputs"]["filename_prefix"] = f"{prefix}/{s.id}"
            self._say(f"▶️  镜 {s.id} · {s.seconds:g}s · {'有首帧' if s.first_frame else '无首帧'}"
                      f"{' + 尾帧' if s.last_frame else ''} · {s.note or ''}".rstrip())
            meta = self._run_one(job, out_path, expect_frames=s.frames(self.fps),
                                 label=f"镜 {s.id}")
            self._say(f"✅ 镜 {s.id} → {os.path.basename(out_path)} · "
                      f"{meta['width']}×{meta['height']} · {meta['duration']:.2f}s · "
                      f"{'带音轨' if meta['has_audio'] else '无音轨'}")
            paths.append(out_path)
        return paths


class MockVideoProvider(VideoProvider):
    """离线桩：用 ffmpeg 把首帧（或纯色）撑成一段真 mp4，方便全流程干跑。

    它不是"假成功"：产物是真视频、有真时长，`film.concat_videos` 能拿它拼出成片，
    所以"小说→分镜→视频→成片"这条链路可以**不依赖显卡**先验一遍。
    画面上会打上 MOCK 字样，避免被当成真片交出去。
    """

    name = "mock"

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or {}
        sub = self.cfg.get("mock") or {}
        self.fps = float(sub.get("fps") or self.cfg.get("fps") or 24)
        self.width = int(sub.get("width") or 640)
        self.height = int(sub.get("height") or 360)
        self.quiet = bool(sub.get("quiet") or self.cfg.get("quiet"))

    def info(self) -> ProviderInfo:
        ok = have_ffmpeg()
        return ProviderInfo(self.name, ok,
                            "本地桩：ffmpeg 生成片段（真视频、非真画面），用于离线验链路"
                            if ok else "需要 ffmpeg 才能生成桩片段", needs_key=False)

    def render(self, shots: list[Shot], *, out_dir: str, force: bool = False) -> list[str]:
        if not shots:
            raise RuntimeError("没有镜头可出：分镜表为空？")
        os.makedirs(out_dir, exist_ok=True)
        paths = []
        for s in shots:
            out = os.path.join(out_dir, f"{s.id}.mp4")
            if os.path.isfile(out) and not force:
                if not self.quiet:
                    print(f"⏭️  镜 {s.id} 已有桩产物，跳过：{out}")
                paths.append(out)
                continue
            secs = max(0.2, s.frames(self.fps) / self.fps)
            src = (["-loop", "1", "-i", s.first_frame] if s.first_frame
                   else ["-f", "lavfi", "-i", f"color=c=0x223344:s={self.width}x{self.height}:r={self.fps}"])
            cmd = [ffmpeg_bin(), "-y", "-loglevel", "error", *src,
                   "-t", f"{secs:.3f}",
                   "-vf", (f"scale={self.width}:{self.height},"
                           f"drawtext=text='MOCK\\ {s.id}':fontcolor=white:fontsize=28:"
                           f"x=20:y=20:box=1:boxcolor=black@0.5"),
                   "-r", str(int(self.fps)), "-pix_fmt", "yuv420p",
                   "-c:v", "libx264", "-crf", "28",
                   "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                   "-shortest", "-c:a", "aac", "-b:a", "96k", out]
            p = subprocess.run(cmd, capture_output=True)
            if p.returncode != 0:
                raise FfmpegError("桩片段生成失败："
                                  + (p.stderr or b"").decode("utf-8", "replace")[-600:])
            if not self.quiet:
                print(f"✅ 镜 {s.id} → {os.path.basename(out)}（桩）· "
                      f"{self.width}×{self.height} · {secs:.2f}s")
            paths.append(out)
        return paths


PROVIDERS = {"comfyui": ComfyUIVideoProvider, "mock": MockVideoProvider}


def get_video_provider(name: str | None = None, cfg: dict | None = None):
    """按名字取视频 Provider；名字不认识就报错并列出可选（不静默回落）。"""
    cfg = cfg or {}
    key = (name or cfg.get("provider") or "comfyui").strip().lower()
    if key not in PROVIDERS:
        raise ValueError(f"不认识的视频 provider：{key}；可选：{', '.join(sorted(PROVIDERS))}")
    return PROVIDERS[key](cfg)


def list_video_providers(cfg: dict | None = None) -> list[ProviderInfo]:
    """所有视频 Provider 的可用性（`doctor` 用）。"""
    out = []
    for key in sorted(PROVIDERS):
        try:
            out.append(PROVIDERS[key](dict(cfg or {})).info())
        except Exception as e:                                        # noqa: BLE001
            out.append(ProviderInfo(key, False, f"初始化失败：{type(e).__name__}: {e}",
                                    needs_key=False))
    return out
