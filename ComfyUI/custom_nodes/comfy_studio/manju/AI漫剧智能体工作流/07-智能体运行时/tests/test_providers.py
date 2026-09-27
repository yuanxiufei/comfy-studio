# -*- coding: utf-8 -*-
"""出图 Provider 的**离线合约测试**（零依赖、无需任何 API Key）。

═══════════════════════════════════════════════════════════════════
为什么需要这个文件
═══════════════════════════════════════════════════════════════════
`openai` / `stability` 两条真实出图路径**没有 Key 就跑不了**。本项目反复吃过
「看起来对、其实没跑过」的亏 —— 尤其是**图生图**：工作流 §4.1 的铁则②要求
「S02–S06 全部以 S01 为 reference_image」，若这段代码是错的且没人知道，
六张图会各自为政（正是原文警告的「空间必然漂移」），而**报告里一切正常**。

解法：用**本地桩 HTTP 服务器**接住请求，断言真实发出的报文。于是
「参考图有没有真的作为**图**发出去」这件事变成**可验证**的，不必等 Key。

运行：`python tests/test_providers.py`
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.image_provider import (MockProvider, OpenAICompatProvider,   # noqa: E402
                               StabilityProvider, png_size, write_png)

# ── 桩服务器 ──

CAPTURED: list[dict] = []          # 每次请求的 path / headers / 原始 body


class _Stub(BaseHTTPRequestHandler):
    """接住出图请求，回一张真 PNG，并**记录原始报文**供断言。"""

    def do_POST(self) -> None:                                   # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        CAPTURED.append({
            "path": self.path,
            "ct": self.headers.get("Content-Type", ""),
            "auth": self.headers.get("Authorization", ""),
            "accept": self.headers.get("Accept", ""),
            "body": body,
        })
        buf = Path(tempfile.gettempdir()) / "_stub_ok.png"
        if not buf.exists():
            write_png(str(buf), 8, 8, lambda x, y: (x * 20 % 256, y * 20 % 256, 128))

        # Stability 要裸图；OpenAI 要 JSON
        # ⚠️ 判据用 `stable-image`（真实路径 `/v2beta/stable-image/generate/core`），
        #    **不是** `stability` —— 后者是 Provider 名，不在 URL 里。
        #    （第一版写错，于是桩回了 JSON，stability 把 JSON 当 PNG 落盘
        #      → png_size 读不出尺寸。这正是本文件存在的意义：错的是**桩**也能被抓出来。）
        if "stable-image" in self.path:
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(buf.read_bytes())
        else:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "data": [{"b64_json": base64.b64encode(buf.read_bytes()).decode()}]
            }).encode())

    def log_message(self, *a) -> None:      # 静音
        pass


def start_stub() -> tuple[HTTPServer, str]:
    srv = HTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


# ── 断言小工具 ──

PASS, FAIL = [], []


def check(label: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(label)
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ← {detail}" if detail and not ok else ""))


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="_provider_test_"))
    try:
        return _run(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run(tmp: Path) -> int:
    ref = tmp / "ref.png"
    write_png(str(ref), 16, 16, lambda x, y: (200, 40, 40))
    ref_bytes = ref.read_bytes()
    out = tmp / "out.png"

    print("── mock：参考图是否**真的流进产物** ──")
    mp = MockProvider()
    a = mp.generate(prompt="same prompt", out_path=str(tmp / "a.png"))[0]
    b = mp.generate(prompt="same prompt", reference=str(ref),
                    out_path=str(tmp / "b.png"))[0]
    check("同 prompt 有/无参考图 → 产物不同（证明参考图参与了生成）",
          Path(a).read_bytes() != Path(b).read_bytes())
    check("带参考图的产物尺寸正确", png_size(b)[:2] == png_size(a)[:2])

    print()
    print("── 参考图缺失 → 必须**报错**，不能静默降级 ──")
    for name, prov in (("mock", MockProvider()),
                       ("openai", OpenAICompatProvider({"api_key": "x"})),
                       ("stability", StabilityProvider({"api_key": "x"}))):
        try:
            prov.generate(prompt="p", out_path=str(tmp / "z.png"),
                          reference=str(tmp / "不存在.png"))
            check(f"{name}：缺失参考图时报错", False, "竟然没报错")
        except Exception as e:                                   # noqa: BLE001
            check(f"{name}：缺失参考图时报错", "参考图不存在" in str(e), str(e)[:70])

    srv, base = start_stub()
    try:
        print()
        print("── openai：**无**参考图 → /images/generations（JSON）──")
        CAPTURED.clear()
        p = OpenAICompatProvider({"api_key": "k", "base_url": base, "model": "m"})
        got = p.generate(prompt="hello", negative_prompt="blurry",
                         width=512, height=512, out_path=str(out))
        c = CAPTURED[-1]
        check("打到 /images/generations", c["path"].endswith("/images/generations"), c["path"])
        check("Content-Type 是 JSON", "application/json" in c["ct"], c["ct"])
        check("negative 併入正文（兼容网关）", b"blurry" in c["body"] and b"Avoid" in c["body"])
        check("响应 b64 被落盘为真 PNG", png_size(got[0]) == (8, 8))

        print()
        print("── openai：**有**参考图 → /images/edits（multipart + 图片字节）──")
        CAPTURED.clear()
        out2 = tmp / "out2.png"
        p.generate(prompt="hello", out_path=str(out2), reference=str(ref))
        c = CAPTURED[-1]
        check("打到 /images/edits", c["path"].endswith("/images/edits"), c["path"])
        check("Content-Type 是 multipart（**未手写**，由 requests 生成 boundary）",
              "multipart/form-data" in c["ct"] and "boundary=" in c["ct"], c["ct"])
        check("报文含字段 image[]", b'name="image[]"' in c["body"])
        check("报文含**参考图的真实字节**（PNG magic）",
              b"\x89PNG\r\n\x1a\n" in c["body"])
        check("Authorization 头正确", c["auth"] == "Bearer k", c["auth"])
        check("参考图落盘为真 PNG", png_size(str(out2)) == (8, 8))

        print()
        print("── openai：字段名可配置（各网关不一）──")
        CAPTURED.clear()
        p2 = OpenAICompatProvider({"api_key": "k", "base_url": base,
                                   "reference_field": "image"})
        p2.generate(prompt="h", out_path=str(tmp / "o3.png"), reference=str(ref))
        check("reference_field=image 时字段名随之改变",
              b'name="image"' in CAPTURED[-1]["body"]
              and b'name="image[]"' not in CAPTURED[-1]["body"])

        print()
        print("── stability：**无**参考图 → files={'none': ''} ──")
        CAPTURED.clear()
        sp = StabilityProvider({"api_key": "k", "base_url": base, "model": "core"})
        o4 = tmp / "o4.png"
        sp.generate(prompt="p", negative_prompt="n", width=1024, height=576,
                    out_path=str(o4))
        c = CAPTURED[-1]
        check("打到 /v2beta/stable-image/generate/core",
              "/v2beta/stable-image/generate/core" in c["path"], c["path"])
        check("Accept: image/*", "image/*" in c["accept"], c["accept"])
        check("有 none 占位字段", b'name="none"' in c["body"])
        check("**无** mode=image-to-image", b"image-to-image" not in c["body"])
        check("aspect_ratio 由尺寸推导为 16:9", b"16:9" in c["body"])
        check("裸图响应被落盘", png_size(str(o4)) == (8, 8))

        print()
        print("── stability：**有**参考图 → mode=image-to-image + strength + 图片 ──")
        CAPTURED.clear()
        o5 = tmp / "o5.png"
        sp.generate(prompt="p", out_path=str(o5), reference=str(ref))
        c = CAPTURED[-1]
        check("带 mode=image-to-image", b"image-to-image" in c["body"])
        check("带 strength（默认 0.55）", b'name="strength"' in c["body"]
              and b"0.55" in c["body"])
        check("带 image 文件字段", b'name="image"' in c["body"])
        check("报文含**参考图的真实字节**", ref_bytes[:8] in c["body"])
        check("**不再**带 none 占位", b'name="none"' not in c["body"])
        check("裸图响应被落盘", png_size(str(o5)) == (8, 8))

        print()
        print("── stability：strength 可配置（越低越贴原图）──")
        CAPTURED.clear()
        sp2 = StabilityProvider({"api_key": "k", "base_url": base, "strength": 0.3})
        sp2.generate(prompt="p", out_path=str(tmp / "o6.png"), reference=str(ref))
        check("strength=0.3 生效", b"0.3" in CAPTURED[-1]["body"])
    finally:
        srv.shutdown()

    print()
    print("=" * 66)
    if FAIL:
        print(f"❌ 失败 {len(FAIL)} 项 / 共 {len(PASS) + len(FAIL)} 项：")
        for f in FAIL:
            print("   ·", f)
        return 1
    print(f"✅ 全部通过 —— {len(PASS)} 项（离线，无需任何 API Key）")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
