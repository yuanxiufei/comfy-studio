# -*- coding: utf-8 -*-
"""两层词表测试（`tr()` = 内置措辞层 + 外挂 CC-CEDICT 层）。

═══════════════════════════════════════════════════════════════════
为什么值得单独测
═══════════════════════════════════════════════════════════════════
2026-09-24 实测踩到三件事，每件都对应下面一条断言：

1. **装完词典以后，词翻得越多、越容易粘成一团**：
   `黄铜护目镜 → brassgoggles`、`亚麻衬衫 → linenshirt`
   （中文没有词间空格）。**装词典之前不明显，装上之后才暴露** ——
   故这条必须有测试，否则以后改 `tr()` 很容易再踩。
2. **内置 vs 外挂的重叠键必须用内置**：外挂把 `亚麻 → flax`、
   `义肢 → artificial limb`、`军装 → military uniform` 也翻了，
   若不设优先级，手工调好的 prompt 措辞会被通用译法悄悄顶掉。
3. **外挂词典损坏时不能静默跳过**：那会让"英文质量"无声退回手写词表水平，
   而用户以为装好了 —— 本项目最忌讳的失败形态。

运行：`python tests/test_dict.py`
"""

from __future__ import annotations

import gzip
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import prompt_engine as pe                       # noqa: E402

PASS, FAIL = [], []


def check(label: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(label)
    print(f"  {'✅' if ok else '❌'} {label}" + (f"   ← {detail}" if detail and not ok else ""))


def reset() -> None:
    """让 `tr()` 重新加载词表（模拟"刚启动"或"换了一份词典"）。"""
    pe._EXTERNAL, pe._EXTERNAL_NOTE, pe._INDEX = None, "", None


def main() -> int:
    print("── ① 外挂词典能挂上，且状态**可见** ──")
    reset()
    ext = pe.external_dict()
    check("外挂词典已加载（条目数 > 1000）", len(ext) > 1000, f"{len(ext)} 条")
    rep = pe.dict_report()
    check("`dict_report()` 报出条目数/来源/许可（可见性）",
          "条" in rep and "CC-CEDICT" in rep and "CC BY-SA" in rep, rep)
    check("所有键都含中文（防误替换英文片段）",
          all(any(ord(c) > 127 for c in k) for k in ext))

    print()
    print("── ② ⭐ **内置优先**（措辞层不被通用译法顶掉）──")
    overlap = sorted(set(ext) & set(pe.ZH2EN))
    check("确实存在重叠键（否则这条断言是空的）", len(overlap) > 20, f"{len(overlap)} 个")
    wrong = [k for k in overlap if pe.tr(k) != pe.ZH2EN[k]]
    check("重叠键一律取**内置**措辞", not wrong,
          f"{len(wrong)} 个不一致：{[(k, pe.tr(k), pe.ZH2EN[k]) for k in wrong[:3]]}")
    for k, want in (("亚麻", "linen"), ("义肢", "prosthetic limb"),
                    ("军装", "military fatigues")):
        if k in ext and ext[k] != want:
            check(f"{k}：内置 {want!r} 压过外挂 {ext[k]!r}", pe.tr(k) == want, pe.tr(k))

    print()
    print("── ③ 外挂**只补空缺**（内置没有的表外词也能译）──")
    for w in ("怀表", "走廊", "码头", "瞭望塔", "勋章", "祭坛", "烟斗", "掌柜", "船工"):
        if w in pe.ZH2EN:
            continue
        check(f"表外词 {w} 由外挂译出", bool(pe.tr(w)) and pe.tr(w) != w, repr(pe.tr(w)))

    print()
    print("── ④ ⭐ 中译英必须**补空格**（实测踩到）──")
    cases = (("黄铜护目镜", "brass goggles"), ("亚麻衬衫", "linen shirt"))
    for s, want in cases:
        got = pe.tr(s)
        check(f"{s!r} → {want!r}（不粘成 {want.replace(' ', '')!r}）",
              got.strip() == want, repr(got))
    check("不会给已是英文的片段乱加空格",
          "  " not in pe.tr("皮革 leather") and pe.tr("皮革 leather").startswith("leather"))

    print()
    print("── ⑤ 最长匹配（整段替换的既有语义不能丢）──")
    check("长词优先（'机械左臂' 不被拆成 '机械'+'左臂'）",
          pe.tr("机械左臂") == pe.ZH2EN["机械左臂"], repr(pe.tr("机械左臂")))
    check("不可译的字原样保留（不丢信息）",
          pe.tr("锈蚀的机械左臂").endswith("cybernetic left arm"), repr(pe.tr("锈蚀的机械左臂")))

    print()
    print("── ⑥ ⭐ 词典**损坏/缺失不能静默**（否则英文质量无声下降）──")
    tmp = Path(tempfile.mkdtemp(prefix="_dict_"))
    real = Path(pe.__file__).resolve().parent.parent / "词库" / "zh2en.json.gz"
    backup = real.with_suffix(".bak")
    try:
        # ① 缺失 → 不崩，且报告里说明"未装"
        shutil.move(str(real), str(backup))
        reset()
        check("词典缺失时不崩", pe.tr("皮革") == "leather")
        check("缺失时 `dict_report()` 说明**未装**并给出补救命令",
              "未装" in pe.dict_report() and "生成词库" in pe.dict_report(),
              pe.dict_report())

        # ② 损坏 → 不崩，且**明确报 ⚠️**（不是静默当没有）
        real.write_bytes(b"this is not gzip")
        reset()
        check("词典损坏时不崩", pe.tr("皮革") == "leather")
        check("损坏时 `dict_report()` **明确报警**（不静默）",
              pe.dict_report().lstrip().startswith("外挂词典：⚠️"), pe.dict_report())
        check("损坏时英文仍只有内置层（不夹中文）",
              not any("\u4e00" <= c <= "\u9fff" for c in pe._en_safe("皮革")))
    finally:
        if real.exists():
            real.unlink()
        shutil.move(str(backup), str(real))
        shutil.rmtree(tmp, ignore_errors=True)
        reset()

    print()
    print("── ⑦ 性能（`tr()` 每份提示词要被调几十次，不能慢）──")
    sample = ["皮质臂套", "破损军用风衣", "黄铜护目镜和亚麻衬衫", "锈蚀的机械左臂"]
    pe.tr("预热")
    t0 = time.time()
    for _ in range(400):
        for s in sample:
            pe.tr(s)
    per = (time.time() - t0) / 1600 * 1000
    check(f"单次调用 < 1 ms（实测 {per:.3f} ms；6 万条词表靠**首字索引**）", per < 1.0)
    # ⚠️ 比的是**长度**不是字符串（第一版写成 `[i][0] >= [i+1][0]`，
    #    那是按字典序比，全等长度时才成立 → 断言恒假。**测试自己写错也会被抓出来**）
    bucket = pe._lookup_index().get("黄") or []
    check(f"索引已建立（同首字 {len(bucket)} 个候选，按**长度**降序）",
          bool(bucket) and all(len(bucket[i][0]) >= len(bucket[i + 1][0])
                               for i in range(len(bucket) - 1)),
          str([kv[0] for kv in bucket[:6]]))

    print()
    print("── ⑧ 生成物自带**署名/许可**（CC BY-SA 4.0 的硬要求）──")
    with gzip.open(real, "rt", encoding="utf-8") as fh:
        blob = json.load(fh)
    meta = blob.get("_meta", {})
    check("`_meta.source` = CC-CEDICT", meta.get("source") == "CC-CEDICT", str(meta.get("source")))
    check("`_meta.license` 写明 CC BY-SA 4.0", "CC BY-SA 4.0" in (meta.get("license") or ""))
    check("`_meta.attribution` 非空（署名）", bool(meta.get("attribution")))
    check("`词库/README.md` 里也有署名与许可（人看得到的那份）",
          "CC BY-SA 4.0" in (real.parent / "README.md").read_text(encoding="utf-8"))

    print()
    print("=" * 66)
    if FAIL:
        print(f"❌ 失败 {len(FAIL)} 项 / 共 {len(PASS) + len(FAIL)} 项：")
        for f in FAIL:
            print("   ·", f)
        return 1
    print(f"✅ 全部通过 —— {len(PASS)} 项")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
