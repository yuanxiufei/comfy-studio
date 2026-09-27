"""成片环节：读视频参数（ffprobe）与拼接（ffmpeg concat）。

为什么这层必须存在、而且必须"读完参数再拼"：
  · MiniMax H3 一次出的是**带音轨**的 mp4（24fps / 1344×768 / AAC），
    相邻片段如果编码参数不一致，`-c copy` 拼出来的片子会在接缝处花屏或直接失败；
  · 所以拼接**先流拷贝**（无损、秒级），失败才回落**重编码**（慢、但能救），
    并把"走的哪条路"如实报出来 —— 不静默重编码，否则用户不知道画质被动了；
  · 拼完必须**回读时长**核对（`sum(各段)` vs 实际），对不上就报错：
    "看着拼成功了、其实少了一段"是这种流水线最典型的假成功。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass

__all__ = ["FfmpegError", "concat_videos", "ffprobe_meta", "have_ffmpeg",
           "still_clip"]


class FfmpegError(RuntimeError):
    """ffmpeg / ffprobe 不在或执行失败 —— 一律带命令与原始输出，便于排错。"""


def _exe(name: str) -> str:
    """找 ffmpeg/ffprobe：先看环境变量，再走 PATH。"""
    env = os.getenv(f"{name.upper()}_BIN") or os.getenv(name.upper())
    if env and os.path.isfile(env):
        return env
    found = shutil.which(name)
    if not found:
        raise FfmpegError(
            f"找不到 {name} —— 成片环节需要它（装 ffmpeg 后重试，"
            f"或用环境变量 {name.upper()}_BIN 指定绝对路径）")
    return found


def ffmpeg_bin() -> str:
    """ffmpeg 可执行文件路径（桩 Provider 也要用，所以对外暴露）。"""
    return _exe("ffmpeg")


def have_ffmpeg() -> bool:
    try:
        _exe("ffmpeg")
        _exe("ffprobe")
        return True
    except FfmpegError:
        return False


def _run(cmd: list[str], *, timeout: float = 1800) -> str:
    p = subprocess.run(cmd, capture_output=True, timeout=timeout)
    out = (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")
    if p.returncode != 0:
        raise FfmpegError(f"命令失败（退出码 {p.returncode}）：\n  {' '.join(cmd)}\n{out[-1200:]}")
    return out


def ffprobe_meta(path: str) -> dict:
    """读一个视频的真实参数；读不到（不是视频/损坏）就报错。"""
    if not os.path.isfile(path):
        raise FfmpegError(f"文件不存在：{path}")
    raw = _run([_exe("ffprobe"), "-v", "error", "-print_format", "json",
                "-show_format", "-show_streams", path])
    try:
        d = json.loads(raw)
    except json.JSONDecodeError as e:                                  # noqa: PERF203
        raise FfmpegError(f"ffprobe 输出不是 JSON：{raw[:300]}") from e
    v = next((s for s in d.get("streams") or [] if s.get("codec_type") == "video"), None)
    a = next((s for s in d.get("streams") or [] if s.get("codec_type") == "audio"), None)
    if not v:
        raise FfmpegError(f"这个文件里没有视频流：{path}")
    num, _, den = (v.get("r_frame_rate") or "0/1").partition("/")
    fps = (float(num) / float(den)) if float(den or 0) else 0.0
    fmt = d.get("format") or {}
    return {
        "path": os.path.abspath(path),
        "width": int(v.get("width") or 0),
        "height": int(v.get("height") or 0),
        "fps": round(fps, 4),
        "nb_frames": int(v.get("nb_frames") or 0),
        "vcodec": v.get("codec_name") or "",
        "acodec": (a or {}).get("codec_name") or "",
        "has_audio": a is not None,
        "duration": float(fmt.get("duration") or v.get("duration") or 0.0),
        "size": int(fmt.get("size") or os.path.getsize(path)),
    }


def still_clip(png: str, seconds: float, out: str, *, fps: float = 24) -> str:
    """把一张静帧撑成一段视频（某镜没出视频时的兜底，画面上会如实标出来）。"""
    if not os.path.isfile(png):
        raise FfmpegError(f"静帧不存在：{png}")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    _run([_exe("ffmpeg"), "-y", "-loglevel", "error", "-loop", "1", "-i", png,
          "-t", f"{max(0.1, float(seconds)):.3f}", "-r", str(int(fps)),
          "-pix_fmt", "yuv420p", "-c:v", "libx264", "-crf", "18", out])
    return out


@dataclass
class ConcatReport:
    out: str
    mode: str                 # "copy" 或 "reencode"
    parts: list[str]
    expect_sec: float
    got_sec: float
    width: int
    height: int
    has_audio: bool

    def line(self) -> str:
        return (f"{os.path.basename(self.out)} · {self.width}×{self.height} · "
                f"{self.got_sec:.2f}s（{len(self.parts)} 段合计 {self.expect_sec:.2f}s）· "
                f"{'流拷贝' if self.mode == 'copy' else '重编码'} · "
                f"{'带音轨' if self.has_audio else '无音轨'}")


def concat_videos(paths: list[str], out: str, *, tolerance: float = 0.6,
                  force_reencode: bool = False, timeout: float = 3600) -> ConcatReport:
    """按顺序把多段视频拼成一部。默认先尝试流拷贝，失败才重编码。

    `tolerance`：总时长允许的偏差（秒）。各段时长由容器元数据给出，
    末段/首段常有零点几秒的时间基误差，所以不能要求分毫不差；
    但超过这个值就说明"少拼了/多拼了"，必须炸。
    """
    paths = [p for p in paths if p]
    if not paths:
        raise FfmpegError("没有可拼接的片段")
    for p in paths:
        if not os.path.isfile(p):
            raise FfmpegError(f"片段不存在：{p}")

    metas = [ffprobe_meta(p) for p in paths]
    expect = sum(m["duration"] for m in metas)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    lst = out + ".concat.txt"
    with open(lst, "w", encoding="utf-8") as f:
        for p in paths:
            f.write("file '" + os.path.abspath(p).replace("\\", "/").replace("'", "'\\''") + "'\n")

    mode = "copy"
    try:
        if force_reencode:
            raise FfmpegError("调用方要求重编码")
        _run([_exe("ffmpeg"), "-y", "-loglevel", "error", "-f", "concat",
              "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", out],
             timeout=timeout)
    except FfmpegError as e:
        mode = "reencode"
        print(f"⚠️  流拷贝拼接失败，回落重编码（画质会二压一次）：{str(e).splitlines()[0]}")
        _run([_exe("ffmpeg"), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
              "-i", lst, "-c:v", "libx264", "-preset", "medium", "-crf", "18",
              "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
              "-movflags", "+faststart", out], timeout=timeout)
    finally:
        if os.path.isfile(lst):
            os.remove(lst)

    got = ffprobe_meta(out)
    if got["duration"] <= 0:
        raise FfmpegError(f"拼出来的片子时长读不出来：{out}")
    if abs(got["duration"] - expect) > max(tolerance, 0.01 * expect):
        raise FfmpegError(
            f"拼接后时长 {got['duration']:.2f}s 与各段合计 {expect:.2f}s 差得太多 —— "
            f"少拼或重复拼了，拒绝交付。分段时间：" +
            ", ".join(f"{os.path.basename(p)}={m['duration']:.2f}s" for p, m in zip(paths, metas)))
    sizes = {(m["width"], m["height"]) for m in metas}
    if len(sizes) > 1 and mode == "copy":
        print(f"⚠️  各段分辨率不一致 {sorted(sizes)}，流拷贝可能出问题；已按实际产物核对："
              f"{got['width']}×{got['height']}")
    return ConcatReport(out=out, mode=mode, parts=paths, expect_sec=expect,
                        got_sec=got["duration"], width=got["width"],
                        height=got["height"], has_audio=got["has_audio"])
