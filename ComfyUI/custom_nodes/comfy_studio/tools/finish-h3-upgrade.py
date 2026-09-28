"""等 H3 权重下完，自动把 06 切到升级档（一次性脚本，放在 tools/ 下）。

为什么要串起来：升 ref2va 那份 DiT 是 34GB 的长任务（本机实测约 20MB/s），中途会长期
停在「04/05 已升、06 没升」的混档状态 —— 而那个状态正是这次要修的毛病本身
（check-workflow-weights.py 会把它报成档位不一致）。所以不把切换留给「记得回来跑一条」。

判据不是「文件尺寸到了」：半截文件和完整文件都占着最终路径。fetch-h3-int8.py 收尾会做
sha256，只在日志里打出 ALL FILES VERIFIED 才算真的好。这里轮询那个标志，然后依次跑
switch 与 check，两份输出都追加进 .cache/h3-06-switch.log，跑完自己收尾。

用法：
    python custom_nodes/comfy_studio/tools/finish-h3-upgrade.py                 # 取 .cache 下最新的 fetch 日志
    python custom_nodes/comfy_studio/tools/finish-h3-upgrade.py <日志路径>       # 指定日志
"""
import subprocess
import sys
import time
from pathlib import Path

import paths

SECONDS_BETWEEN_POLLS = 30
GIVE_UP_AFTER = 6 * 3600
DONE_MARKER = "ALL FILES VERIFIED"
TARGET = "06_视频_r2v_多镜连贯.json"

ROOT = paths.comfy_root()
CACHE = ROOT / ".cache"
REPORT = CACHE / "h3-06-switch.log"


def newest_fetch_log():
    """fetch 的 stdout 日志。排除 .err.log：curl 的进度条走 stderr，是另一个文件。"""
    logs = [p for p in CACHE.glob("h3-int8-fetch*.log") if not p.name.endswith(".err.log")]
    if not logs:
        raise SystemExit("找不到 fetch 日志，先跑 custom_nodes/comfy_studio/tools/fetch-h3-int8.py")
    return max(logs, key=lambda p: p.stat().st_mtime)


def wait_for(log):
    deadline = time.time() + GIVE_UP_AFTER
    print("等下载脚本宣告完成：{}".format(log), flush=True)
    while time.time() < deadline:
        if log.is_file() and DONE_MARKER in log.read_text(encoding="utf-8", errors="replace"):
            print("  看到 {!r}".format(DONE_MARKER), flush=True)
            return True
        time.sleep(SECONDS_BETWEEN_POLLS)
    print("  等满 {} 小时仍未看到 {!r}，不再等".format(GIVE_UP_AFTER // 3600, DONE_MARKER), flush=True)
    return False


def run(*args):
    """跑一个 .cache 下的脚本，stdout+stderr 一并落到报告里。"""
    cmd = [sys.executable] + list(args)
    print("\n$ python {}".format(" ".join(args)), flush=True)
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    text = (proc.stdout or "") + (proc.stderr or "")
    print(text, flush=True)
    with REPORT.open("a", encoding="utf-8") as handle:
        handle.write("\n$ python {}\n\n{}".format(" ".join(args), text))
    return proc.returncode


def main():
    log = Path(sys.argv[1]) if len(sys.argv) > 1 else newest_fetch_log()
    REPORT.write_text("=== finish-h3-upgrade 开始 ===\n", encoding="utf-8")
    if not wait_for(log):
        run("custom_nodes/comfy_studio/tools/check-workflow-weights.py")
        raise SystemExit("下载没等到完成，未切换；报告见 {}".format(REPORT))

    rc = run("custom_nodes/comfy_studio/tools/switch-h3-weights.py", "upgraded", TARGET)
    if rc != 0:
        raise SystemExit("切换失败（rc={}），报告见 {}".format(rc, REPORT))
    rc = run("custom_nodes/comfy_studio/tools/check-workflow-weights.py")
    print("\n=== 完成，报告 {}".format(REPORT), flush=True)
    sys.exit(rc)


if __name__ == "__main__":
    main()
