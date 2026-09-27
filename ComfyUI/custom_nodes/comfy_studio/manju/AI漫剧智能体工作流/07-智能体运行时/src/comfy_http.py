"""ComfyUI 的四个 HTTP 原语（纯标准库）—— 出图 / 出视频两条链路共用一份。

为什么单独抽出来：
  · 出图（`image_provider.ComfyUIProvider`）与出视频（`video_provider.ComfyUIVideoProvider`）
    面对的是**同一台** ComfyUI，`/prompt`、`/history`、`/view`、`/upload/image` 的用法一模一样；
  · 之前这套逻辑只长在出图的类里。视频侧如果要"再抄一遍"，两份就会各自漂移
    （比如一边改了上传的 multipart 边界名、另一边没改），排错时会互相干扰。
  · 所以：**一处实现**，两个 Provider 都调这里。出图那边的三个方法体改成一行转发，
    行为与原实现逐字等价（`tests/test_comfyui_provider.py` 钉着它）。

`/object_info` 也在这一层：它是**运行时的输入顺序事实来源**，出视频靠它修位置错位，
出图将来也能用。
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
import uuid

__all__ = ["http_get", "post_json", "upload_image", "view_blob",
           "object_info", "system_stats"]


def http_get(base_url: str, path: str, *, timeout: float = 15) -> bytes:
    """GET 一段字节（`/view` 拿文件、`/history` 拿状态都走这里）。"""
    with urllib.request.urlopen(f"{base_url}{path}", timeout=timeout) as r:
        return r.read()


def post_json(base_url: str, path: str, payload: dict, *, timeout: float = 30) -> dict:
    """POST 一段 JSON 并解析回包（`/prompt` 提交、`/object_info` 也吃这个）。"""
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def upload_image(base_url: str, path: str, *, timeout: float = 60) -> str:
    """把一张本地图 POST 到 `/upload/image`，返回 ComfyUI 侧的引用名。

    返回的是 **相对 ComfyUI `input/` 目录**的路径（如 `minimax/f01.png`）——
    因为 Director 那边就是拿这个名字去 `folder_paths.get_input_directory()` 拼的
    （`director/plan.py: load_reference_tensor`）。
    """
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
        f"{base_url}/upload/image", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        res = json.loads(r.read().decode("utf-8"))
    sub = res.get("subfolder") or ""
    return f"{sub}/{res['name']}" if sub else res["name"]


def view_blob(base_url: str, ref: dict, *, timeout: float = 120) -> bytes:
    """按 `/history` 里给出的 `{filename, subfolder, type}` 把产物字节取回来。"""
    q = urllib.parse.urlencode({"filename": ref["filename"],
                                "subfolder": ref.get("subfolder", ""),
                                "type": ref.get("type", "output")})
    return http_get(base_url, f"/view?{q}", timeout=timeout)


def object_info(base_url: str, class_type: str, *, timeout: float = 20) -> dict:
    """取某个节点类型的声明（输入顺序 / 默认值 / 取值域）。

    出视频靠它把 `widgets_values` **按名字**对上号：ComfyUI 前端另存的工作流里，
    widget 值是按**位置**存的，而位置的真相在节点声明里 —— 实测
    `MiniMaxH3Director` 存了 21 个值、声明里只有 20 个 widget，
    多出来的是前端 JS 侧控件（值 `"fixed"`），于是从 `frame_rate` 起全体后移一位。
    """
    raw = http_get(base_url, f"/object_info/{urllib.parse.quote(class_type)}", timeout=timeout)
    return json.loads(raw.decode("utf-8")).get(class_type) or {}


def system_stats(base_url: str, *, timeout: float = 6) -> dict:
    """`/system_stats`：探活 + 拿 ComfyUI 版本（`doctor` 与 Provider.info 都用）。"""
    return json.loads(http_get(base_url, "/system_stats", timeout=timeout).decode("utf-8"))
