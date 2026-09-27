# -*- coding: utf-8 -*-
"""从 **CC-CEDICT** 生成「中文词 → 英文」词典。

═══════════════════════════════════════════════════════════════════
为什么要这个脚本
═══════════════════════════════════════════════════════════════════
英文提示词需要「中文词 → 英文」，而项目原来靠 `prompt_engine.ZH2EN`
**手写 168 条**（+ `OCCUPATION_EN` 43 条）。手写的根本问题不是"少"，
而是**它是一道识别闸门**：查不到的词会被原样留在英文 prompt 里（或被迫省略），
于是「任何一部小说都行」这条要求，实际被"我们手写了多少词"卡住。

⭐ 解法：**用现成词典，而不是继续手写**。
CC-CEDICT 是社区维护的免费汉英词典（**12.5 万条**），本脚本把它清洗成
「中文词 → 英文名词短语」的映射，供 `prompt_engine.tr()` 作为**可选外挂层**查用。

⚠️ 许可：CC-CEDICT 采用 **CC BY-SA 4.0**，**必须署名**。
故生成物里带 `_meta`，仓库里另有 `data/README.md` 写明来源与许可。

═══════════════════════════════════════════════════════════════════
清洗规则（每一条都对应实测踩到的问题）
═══════════════════════════════════════════════════════════════════
CC-CEDICT 是**给人读的词典**，不是给 prompt 用的词表，直接取义项会得到
「to do sth on behalf of sb else」「Xinyu, prefecture-level city in Jiangxi」这种
东西。故逐项清洗（括号内的现象都是实测踩到的，最初一版漏掉了这些词）：

  · 分离符不止 `/`，**还有 `;`**            → 否则「护目镜/走廊/码头」全被丢
  · 只取**第 1 个义项**会漏                 → 「长袍」第 1 项含中文，第 2 项才是 gown
  · 义项含**括号注记**要剥掉                → `(old) foreign firm` → `foreign firm`
  · 义项含**中文**要截断到中文前            → `brass (alloy of copper 銅|铜…)` → `brass`
  · 义项**过长**要截到首个逗号前            → `cheongsam, a traditional Chinese dress…`
  · **动词义项**（`to …`）不要              → 我们要的是名词短语
  · **专有名词**要排除                      → 结构信号：CC-CEDICT 里专有名词的
                                              **拼音首字母大写**（`Xin1 yu2 Shi4` = 新余市）
                                              —— 不用词表就能排掉人名/地名

用法：
    python 工具/生成词库.py                    # 自动下载（约 4 MB，慢）
    python 工具/生成词库.py --源 cedict.txt     # 用本地文件（推荐，可复现）
    python 工具/生成词库.py --预览              # 只看统计与样例，不写文件
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_URL = ("https://www.mdbg.net/chinese/export/cedict/"
           "cedict_1_0_ts_utf-8_mdbg.txt.gz")
# ⚠️ 目录名**不能叫 `data/`**：仓库根的 `.gitignore` 有一行 `data/`（为根目录那
#    4.3 GB 用户素材设的，且**没有锚定**），会连带忽略**任何层级**的 `data/`。
#    后果很隐蔽：词典不入库，而将来往该目录加文件也会**静默不入库**。
#    故改用项目自己的中文目录名（与 `工具/` 一致）。
OUT_DEFAULT = ROOT / "词库" / "zh2en.json.gz"
CACHE = Path(tempfile.gettempdir()) / "cedict.txt"

HAN = re.compile(r"[\u4e00-\u9fff]")

# 义项里的这些词说明「不是我们要的具体名词」（用法注记 / 专名标记 / 虚词）
BAD = re.compile(
    r"\b(lit|fig|surname|variant|see|abbr|old|archaic|dialect|used in|"
    r"also written|erhua|onomat|classifier|suffix|prefix|particle|idiom|"
    r"proverb|buddhism|christianity|myth|folklore)\b", re.I)

ENTRY = re.compile(r"^(\S+)\s+(\S+)\s+\[([^\]]*)\]\s+/(.*)/\s*$")


def clean(cand: str) -> str:
    """把一个义项片段清成可用的英文名词短语；不合格返回空串。"""
    g = re.sub(r"\([^)]*\)", " ", cand)        # 剥掉所有括号注记（含中文的）
    g = HAN.split(g)[0]                         # 截断到第一个中文字前
    g = g.split("|")[0]
    g = g.split(",")[0]                         # 取第一个义项片段
    g = re.sub(r"[^A-Za-z0-9\-' ]", " ", g)
    g = re.sub(r"\s+", " ", g).strip(" -'")
    if not g or not g[0].islower():             # 大写开头 → 多半是专名/缩写
        return ""
    if len(g) > 30 or len(g.split()) > 4:
        return ""
    if BAD.search(g) or g.lower().startswith("to "):
        return ""
    return g


def parse(line: str):
    """`傳統 简体 [pin1 yin1] /义1;义2/义3/` → `(简体, 拼音, [义项…])`。"""
    m = ENTRY.match(line)
    if not m:
        return None
    return m.group(2), m.group(3), [x for x in re.split(r"[/;]", m.group(4)) if x.strip()]


def build(src: Path, min_len: int = 2, max_len: int = 4) -> tuple[dict, dict]:
    out: dict[str, str] = {}
    st = {"lines": 0, "proper": 0, "shape": 0, "nomatch": 0, "kept": 0}
    with open(src, encoding="utf-8", newline="") as fh:
        for raw in fh:
            line = raw.rstrip("\r\n")
            if not line.strip() or line.startswith("#"):
                continue
            st["lines"] += 1
            r = parse(line)
            if not r:
                st["nomatch"] += 1
                continue
            word, pinyin, glosses = r
            if not (min_len <= len(word) <= max_len) or HAN.sub("", word):
                st["shape"] += 1
                continue
            # ⭐ 专有名词的**结构信号**：拼音首字母大写（Xin1 yu2 Shi4 = 新余市）
            if pinyin[:1].isupper():
                st["proper"] += 1
                continue
            for cand in glosses:
                g = clean(cand)
                if g:
                    st["kept"] += 1
                    # 同词多义：留**最短**的（最短通常最具体）
                    if word not in out or len(g) < len(out[word]):
                        out[word] = g
                    break
    return out, st


def ensure_source(arg: str | None) -> Path:
    if arg:
        p = Path(arg)
        if not p.is_file():
            sys.exit(f"❌ 找不到源文件：{arg}")
        return p
    if CACHE.is_file():
        print(f"  用缓存：{CACHE}")
        return CACHE
    print(f"  下载 CC-CEDICT（约 4 MB，可能要 30–60 秒）…")
    t0 = time.time()
    with urllib.request.urlopen(SRC_URL, timeout=180) as r:
        blob = r.read()
    text = gzip.decompress(blob).decode("utf-8")
    CACHE.write_text(text, encoding="utf-8", newline="")
    print(f"  完成 {len(blob) / 1048576:.2f} MB / {time.time() - t0:.1f}s → {CACHE}")
    return CACHE


def main() -> int:
    ap = argparse.ArgumentParser(description="从 CC-CEDICT 生成「中文词→英文」词典")
    ap.add_argument("--源", dest="src", help="本地 CC-CEDICT 文本文件（不给则自动下载）")
    ap.add_argument("--输出", dest="out", default=str(OUT_DEFAULT))
    ap.add_argument("--最短", dest="mn", type=int, default=2)
    ap.add_argument("--最长", dest="mx", type=int, default=4)
    # ⚠️ 中文选项名必须显式给 `dest` —— argparse 不会把「预览」转成 `preview`
    #    （第一版漏了，于是 `a.preview` 直接 AttributeError）
    ap.add_argument("--预览", dest="preview", action="store_true",
                    help="只打印统计与样例，不写文件")
    a = ap.parse_args()

    src = ensure_source(a.src)
    print(f"  解析 {src} …")
    d, st = build(src, a.mn, a.mx)
    print(f"    词条行 {st['lines']} ｜ 专有名词剔除 {st['proper']} ｜ "
          f"字数不符 {st['shape']} ｜ 解析失败 {st['nomatch']}")
    print(f"    ✅ 生成 {len(d)} 条（中文词 {a.mn}–{a.mx} 字）")

    print()
    print("  抽样：")
    import random
    random.seed(11)
    for w in random.sample(list(d), 8):
        print(f"    {w:6s} → {d[w]}")

    if a.preview:
        return 0

    payload = {
        "_meta": {
            "source": "CC-CEDICT",
            "source_url": SRC_URL,
            "license": "CC BY-SA 4.0",
            "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
            "attribution": "CC-CEDICT © MDBG / contributors (CC BY-SA 4.0)",
            "generated_by": "工具/生成词库.py",
            "generated_at": time.strftime("%Y-%m-%d"),
            "word_len": f"{a.mn}-{a.mx}",
            "entries": len(d),
            "note": "本文件是**衍生作品**（清洗/筛选自 CC-CEDICT），"
                    "依 CC BY-SA 4.0 同样以 CC BY-SA 4.0 提供。",
        },
        "zh2en": d,
    }
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    blob = gzip.compress(raw, 9)
    out.write_bytes(blob)
    print()
    print(f"  ✅ 写出 {out}")
    print(f"     JSON {len(raw) / 1024:.1f} KB → gzip {len(blob) / 1024:.1f} KB "
          f"（`gzip` 是标准库，运行时**零第三方依赖**）")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
