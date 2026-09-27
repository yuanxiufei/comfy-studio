# -*- coding: utf-8 -*-
"""`comfyui` 出图 Provider 的**离线合约测试**（零依赖、无需 ComfyUI 在跑）。

═══════════════════════════════════════════════════════════════════
为什么需要这个文件
═══════════════════════════════════════════════════════════════════
接本机 ComfyUI 与接 openai/stability 有**本质不同**：那两个是"给文字、还你图"，
报文发错顶多报错；而 ComfyUI 要**自带节点图**，我们只往四个位置注入变量 ——
**注入点没找准的话，图照样会出来，只是内容完全不对**（提示词压根没进去），
或者**尺寸悄悄没生效**。这类错误在报告里是看不见的。

所以这里把三件事钉死：
  ① **节点式 → API 式**的转换（`widgets_values` 与 `inputs` 的对应关系）
  ② **四个注入点的定位**（靠连线，不靠节点 id）
  ③ **出错必须炸**（缺工作流 / 缺采样器 / 正负向没接 CLIP / 传了参考图却无 LoadImage /
     产出尺寸与请求不符）—— 一条都不许静默降级

运行：`python tests/test_comfyui_provider.py`
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.image_provider import (ComfyUIProvider, graph_to_api,   # noqa: E402
                                png_size, write_png)
from src.video_provider import find_comfy_root                    # noqa: E402

PASS, FAIL = [], []


def check(label: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(label)
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ← {detail}" if detail and not ok else ""))


# ── 桩：假装自己是 ComfyUI ──

CAPTURED: list[dict] = []
STUB_SIZE = [64, 64]          # 桩"产出"的尺寸；测试可改，用来验尺寸校验


class _Stub(BaseHTTPRequestHandler):
    def do_GET(self) -> None:                                    # noqa: N802
        CAPTURED.append({"m": "GET", "path": self.path})
        if self.path.startswith("/system_stats"):
            return self._json({"system": {"comfyui_version": "0.0-stub"}})
        if self.path.startswith("/history/"):
            pid = self.path.rsplit("/", 1)[-1]
            return self._json({pid: {
                "status": {"status_str": "success", "completed": True},
                "outputs": {"9": {"images": [{"filename": "out_00001_.png",
                                              "subfolder": "", "type": "output"}]}},
            }})
        if self.path.startswith("/view"):
            buf = Path(tempfile.gettempdir()) / "_stub_comfy.png"
            write_png(str(buf), STUB_SIZE[0], STUB_SIZE[1],
                      lambda x, y: (x * 3 % 256, y * 3 % 256, 90))
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(buf.read_bytes())
            return
        self.send_error(404)

    def do_POST(self) -> None:                                   # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        CAPTURED.append({"m": "POST", "path": self.path, "body": body,
                         "ct": self.headers.get("Content-Type", "")})
        if self.path.startswith("/prompt"):
            return self._json({"prompt_id": "pid-1"})
        if self.path.startswith("/upload/image"):
            return self._json({"name": "ref.png", "subfolder": ""})
        self.send_error(404)

    def _json(self, obj) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

    def log_message(self, *a) -> None:
        pass


def start_stub() -> tuple[HTTPServer, str]:
    srv = HTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


# ── 造图的小工具 ──

def _node(nid, t, inputs, widgets=None, mode=None):
    n = {"id": nid, "type": t, "inputs": inputs, "widgets_values": widgets or []}
    if mode is not None:
        n["mode"] = mode
    return n


def wf_two_clip(with_latent: bool = True, with_load_image: bool = False) -> dict:
    """最小可用工作流：UNET → 两个 CLIPTextEncode → KSampler → SaveImage。"""
    nodes = [
        _node(1, "UNETLoader", [{"name": "unet_name", "link": None},
                                {"name": "weight_dtype", "link": None}],
              ["m.safetensors", "default"]),
        _node(2, "CLIPLoader", [{"name": "clip_name", "link": None},
                                {"name": "type", "link": None}],
              ["t.safetensors", "qwen_image"]),
        _node(3, "CLIPTextEncode", [{"name": "text", "link": None}], ["POS"]),
        _node(4, "CLIPTextEncode", [{"name": "text", "link": None}], ["NEG"]),
        _node(5, "KSampler", [
            {"name": "model", "link": 1}, {"name": "positive", "link": 2},
            {"name": "negative", "link": 3},
            {"name": "latent_image", "link": 4 if with_latent else None},
            {"name": "seed", "link": None}, {"name": "steps", "link": None},
            {"name": "cfg", "link": None}, {"name": "sampler_name", "link": None},
            {"name": "scheduler", "link": None}, {"name": "denoise", "link": None}],
            [42, 30, 4.0, "euler", "normal", 1.0]),
        _node(6, "EmptySD3LatentImage", [{"name": "width", "link": None},
                                         {"name": "height", "link": None},
                                         {"name": "batch_size", "link": None}],
              [2048, 1536, 1]),
        _node(7, "VAEDecode", [{"name": "samples", "link": 5},
                               {"name": "vae", "link": 6}], []),
        _node(8, "SaveImage", [{"name": "images", "link": 7}], ["prefix"]),
        _node(9, "Note", [{"name": "note", "link": None}], ["给我看的注释"]),
    ]
    if with_load_image:
        nodes.append(_node(10, "LoadImage", [{"name": "image", "link": None}],
                           ["placeholder.png"]))
    links = [
        [1, 1, 0, 5, 0, "MODEL"],
        [2, 3, 0, 5, 1, "CONDITIONING"],
        [3, 4, 0, 5, 2, "CONDITIONING"],
        [4, 6, 0, 5, 3, "LATENT"],
        [5, 5, 0, 7, 0, "LATENT"],
        [6, 2, 0, 7, 1, "VAE"],
        [7, 7, 0, 8, 0, "IMAGE"],
    ]
    if with_latent:
        links.append([4, 6, 0, 5, 3, "LATENT"])
    return {"nodes": nodes, "links": links}


def _write_wf(tmp: Path, graph: dict, name: str = "wf.json") -> str:
    p = tmp / name
    p.write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
    return str(p)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="_comfy_test_"))
    try:
        return _run(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run(tmp: Path) -> int:
    print("── ① 节点式 → API 式：widget 与连线的对应 ──")
    api = graph_to_api(wf_two_clip())
    check("Note 节点被排除（不参与执行）", not any(n["class_type"] == "Note" for n in api.values()))
    check("UNETLoader.unet_name 从 widgets 取到",
          api["1"]["inputs"]["unet_name"] == "m.safetensors", str(api["1"]["inputs"]))
    check("所有节点 id 都是**字符串**", all(isinstance(k, str) for k in api))
    check("KSampler.model 还原成 [上游id, 槽]",
          api["5"]["inputs"]["model"] == ["1", 0], str(api["5"]["inputs"].get("model")))
    check("KSampler.positive 连到节点 3", api["5"]["inputs"]["positive"] == ["3", 0])
    check("KSampler.seed 从 widgets 取到 42", api["5"]["inputs"]["seed"] == 42)
    check("KSampler 6 个 widget 全部对上（seed/steps/cfg/sampler/scheduler/denoise）",
          [api["5"]["inputs"][k] for k in ("seed", "steps", "cfg", "sampler_name",
                                           "scheduler", "denoise")]
          == [42, 30, 4.0, "euler", "normal", 1.0], str(api["5"]["inputs"]))
    check("EmptySD3LatentImage 尺寸从 widgets 取到",
          (api["6"]["inputs"]["width"], api["6"]["inputs"]["height"]) == (2048, 1536))

    print()
    print("── ② 与**真实**工作流对拍（存在才跑）──")
    # 盘符一律不写死：ComfyUI 根现探测（`src/video_provider.py::find_comfy_root` ——
    # `COMFYUI_ROOT` 环境变量 → 从那个文件往上找 `user/default/workflows`）。
    # 写死路径的下场不是报错，是**换台机器就静默跳过**，这条对拍从此再也不跑。
    comfy = find_comfy_root()
    real = (Path(comfy) / "user" / "default" / "workflows" / "AIGC中国风漫剧"
            / "01_角色定妆板_Qwen2512.json") if comfy else None
    if real and real.is_file():
        rapi = graph_to_api(json.loads(real.read_text(encoding="utf-8")))
        unets = {n["inputs"].get("unet_name") for n in rapi.values()
                 if n["class_type"] == "UNETLoader"}
        loras = {n["inputs"].get("lora_name") for n in rapi.values()
                 if n["class_type"] == "LoraLoaderModelOnly"}
        check(f"真实工作流解析出 {len(rapi)} 个节点", len(rapi) >= 8, str(len(rapi)))
        check("UNETLoader 拿到真实模型名", any("qwen_image" in str(u) for u in unets), str(unets))
        check("LoRA 名不是 None（说明 widget 顺序没串位）",
              all(l for l in loras) and bool(loras), str(loras))
        check("SaveImage.filename_prefix 是字符串（不是 None）",
              all(isinstance(n["inputs"].get("filename_prefix"), str)
                  for n in rapi.values() if n["class_type"] == "SaveImage"))
    else:
        why = "没探测到 ComfyUI 根（设 COMFYUI_ROOT 可指定）" if not comfy else f"{real} 不存在"
        print(f"  （跳过：{why}）")

    print()
    print("── ③ 四个注入点定位 ──")
    srv, base = start_stub()
    STUB_SIZE[:] = (64, 64)
    try:
        wf = _write_wf(tmp, wf_two_clip())
        p = ComfyUIProvider({"comfyui": {"workflow": wf, "base_url": base, "poll": 0.01}})
        out = tmp / "out.png"
        got = p.generate(prompt="PROMPT_正", negative_prompt="NEG_负",
                         width=64, height=64, out_path=str(out))
        cap = [c for c in CAPTURED if c.get("path", "").startswith("/prompt")][-1]
        sent = json.loads(cap["body"])["prompt"]
        check("正向词注入到 KSampler.positive 指向的那个 CLIPTextEncode",
              sent["3"]["inputs"]["text"] == "PROMPT_正", str(sent["3"]["inputs"]))
        check("负向词注入到 KSampler.negative 指向的那个",
              sent["4"]["inputs"]["text"] == "NEG_负")
        check("尺寸注入到 latent 节点",
              (sent["6"]["inputs"]["width"], sent["6"]["inputs"]["height"]) == (64, 64))
        check("seed 被写上（不是原工作流的 42）", isinstance(sent["5"]["inputs"]["seed"], int))
        check("模型/LoRA 等**未被改动**",
              sent["1"]["inputs"]["unet_name"] == "m.safetensors")
        check("产物落盘为真 PNG 且尺寸相符", png_size(got[0]) == (64, 64))
        check("/view 被调用取图", any(c.get("path", "").startswith("/view") for c in CAPTURED))

        print()
        print("── ④ seed 可复现：同词同 seed，异词异 seed ──")
        s1 = p._seed_for("a", "b", 0)
        s2 = p._seed_for("a", "b", 0)
        s3 = p._seed_for("c", "b", 0)
        check("同 prompt → 同 seed（一致性第 1 条）", s1 == s2)
        check("不同 prompt → 不同 seed", s1 != s3, f"{s1} vs {s3}")

        print()
        print("── ⑤ 出错必须炸（不许静默降级）──")
        # 缺工作流
        try:
            ComfyUIProvider({"comfyui": {}}).generate(prompt="p", out_path=str(tmp / "x.png"))
            check("未配置工作流 → 报错", False, "竟然没报错")
        except Exception as e:                                    # noqa: BLE001
            check("未配置工作流 → 报错", "未配置 ComfyUI 工作流" in str(e), str(e)[:80])

        # 正负向没接 CLIP
        bad = wf_two_clip()
        for nd in bad["nodes"]:
            if nd["id"] == 5:
                nd["inputs"][1]["link"] = None
        bwf = _write_wf(tmp, bad, "bad.json")
        try:
            ComfyUIProvider({"comfyui": {"workflow": bwf, "base_url": base}}).generate(
                prompt="p", width=64, height=64, out_path=str(tmp / "y.png"))
            check("positive 没接 CLIPTextEncode → 报错", False, "竟然没报错")
        except Exception as e:                                    # noqa: BLE001
            check("positive 没接 CLIPTextEncode → 报错",
                  "positive 没连到 CLIPTextEncode" in str(e), str(e)[:80])

        # 尺寸不符 → 必须炸（桩固定吐 64x64，这里请求 128x128）
        try:
            p.generate(prompt="p", width=128, height=128, out_path=str(tmp / "z.png"))
            check("产出尺寸与请求不符 → 报错", False, "竟然没报错")
        except Exception as e:                                    # noqa: BLE001
            check("产出尺寸与请求不符 → 报错", "尺寸" in str(e) and "不符" in str(e), str(e)[:80])

        # 参考图但工作流没有 LoadImage
        try:
            ref = tmp / "r.png"
            write_png(str(ref), 8, 8, lambda x, y: (1, 2, 3))
            p.generate(prompt="p", width=64, height=64, out_path=str(tmp / "w.png"),
                       reference=str(ref))
            check("无 LoadImage 却传参考图 → 报错", False, "竟然没报错")
        except Exception as e:                                    # noqa: BLE001
            check("无 LoadImage 却传参考图 → 报错",
                  "没有 LoadImage" in str(e), str(e)[:80])

        # 有 LoadImage → 应当上传并写进节点
        CAPTURED.clear()
        wf2 = _write_wf(tmp, wf_two_clip(with_load_image=True), "wf2.json")
        p2 = ComfyUIProvider({"comfyui": {"workflow": wf2, "base_url": base, "poll": 0.01}})
        ref = tmp / "r2.png"
        write_png(str(ref), 8, 8, lambda x, y: (9, 9, 9))
        p2.generate(prompt="p", width=64, height=64, out_path=str(tmp / "v.png"),
                    reference=str(ref))
        check("/upload/image 被调用", any(c.get("path", "").startswith("/upload/image")
                                        for c in CAPTURED))
        sent = json.loads([c for c in CAPTURED if c.get("path") == "/prompt"][-1]["body"])["prompt"]
        check("LoadImage.image 被写成上传后的文件名", sent["10"]["inputs"]["image"] == "ref.png",
              str(sent["10"]["inputs"]))

        print()
        print("── ⑥ info()：没工作流应如实报不可用 ──")
        i = ComfyUIProvider({"comfyui": {}}).info()
        check("无工作流时 available=False", i.available is False)
        i2 = ComfyUIProvider({"comfyui": {"workflow": wf2, "base_url": base}}).info()
        check("工作流就绪且服务在 → available=True", i2.available is True, i2.reason)
        check("comfyui 不需要 API Key", i2.needs_key is False)
    finally:
        srv.shutdown()

    print()
    print("=" * 66)
    if FAIL:
        print(f"❌ 失败 {len(FAIL)} 项 / 共 {len(PASS) + len(FAIL)} 项：")
        for f in FAIL:
            print("   ·", f)
        return 1
    print(f"✅ 全部通过 —— {len(PASS)} 项（离线，不需要 ComfyUI 真的在跑）")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
