# -*- coding: utf-8 -*-
"""§六「漂移检测」的测试（零依赖、无需 Key）。

═══════════════════════════════════════════════════════════════════
为什么这个文件必须存在
═══════════════════════════════════════════════════════════════════
本项目已有一条血泪通则：**「检查器报全 ✅ 时不要高兴，先问它有没有可能报 ❌」**
—— 一个永远全过的检查器等于没有（第 ⑤ 轮实测：违反模板规则却 5 项全过）。

所以本测试的重点**不是**"正常情况通过"，而是**故意注入每一种漂移，证明它真的会报**：
未登记 ID · 格式非法 · 一号两类型 · 两张单子不一致 · 外来前缀不误报 · 派生后缀不误报。

运行：`python tests/test_drift.py`
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import drift   # noqa: E402

PASS, FAIL = [], []


def check(label: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(label)
    print(f"  {'✅' if ok else '❌'} {label}" + (f"   ← {detail}" if detail and not ok else ""))


def make_project(tmp: Path, issued: dict, dirs: list[str]) -> Path:
    (tmp / "config").mkdir(parents=True, exist_ok=True)
    (tmp / "assets").mkdir(parents=True, exist_ok=True)
    for d in dirs:
        (tmp / "assets" / d).mkdir(parents=True, exist_ok=True)
    (tmp / "config" / "id_registry.json").write_text(
        json.dumps({"issued": issued}, ensure_ascii=False), encoding="utf-8")
    return tmp


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="_drift_test_"))
    try:
        return _run(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run(tmp: Path) -> int:
    issued = {
        "CHR_001": {"type": "character"},
        "CHR_002": {"type": "character"},
        "ENV_001": {"type": "environment"},
        "EXP_CHR001_愤怒": {"type": "expression"},
    }
    root = make_project(tmp, issued,
                        ["characters/CHR_001", "characters/CHR_002",
                         "scenes/ENV_001", "expressions/EXP_CHR001_愤怒"])
    known, gap = drift.load_registry(root)

    print("── 基线：全部登记、格式合规 ──")
    rep = drift.check_text("角色 CHR_001 与 CHR_002，场景 ENV_001。", known)
    check("干净文本 → ok", rep.ok, str(rep.unregistered))
    check("总表 4 条", rep.known == 4, str(rep.known))
    check("两张单子一致（无 gap）", not gap, str(gap))

    print()
    print("── ❌ 必须报出：未登记 ID（自造 / 笔误 / 引用不存在的资产）──")
    rep = drift.check_text("角色 CHR_099 出现在这一镜。", known)
    check("CHR_099 未登记 → 报出", not rep.ok and "CHR_099" in rep.unregistered,
          str(rep.unregistered))
    rep = drift.check_text("参考 CHR_003 的设定。", known)
    check("CHR_003（号位存在但未登记）→ 报出", "CHR_003" in rep.unregistered)

    print()
    print("── ❌ 必须报出：ID 格式不合 §四 ──")
    rep = drift.check_text("这是 CHR_1（只 1 位）。", known)
    check("CHR_1 → 格式非法", any(t == "CHR_1" for t, _ in rep.malformed), str(rep.malformed))
    rep = drift.check_text("这是 ENV_01（只 2 位）。", known)
    check("ENV_01 → 格式非法", any(t == "ENV_01" for t, _ in rep.malformed))
    rep = drift.check_text("蓝图字面 CHAR-001。", known)
    check("总表是工作流字面时，CHAR-001 → 确实未登记（该报）",
          "CHAR-001" in rep.unregistered, str(rep.unregistered))
    check("同时给出「这是蓝图字面、非自造」的说明",
          any(t == "CHAR-001" for t, _ in rep.style_mismatch), str(rep.style_mismatch))
    rep = drift.check_text("蓝图字面 CHAR-001。", {"CHAR-001"})
    check("总表本身用蓝图字面时 → **不报未登记**，只提示风格（避免误报）",
          rep.ok and len(rep.style_mismatch) == 1, str(rep.unregistered))

    print()
    print("── ✅ 不该误报：派生后缀 / 表情 / 外来前缀 ──")
    rep = drift.check_text("六角度：ENV_001_S01..ENV_001_S06，全景 ENV_001_PanoramaBase。",
                           known)
    check("ENV_001_S01 / _PanoramaBase（派生）→ 不报未登记", rep.ok, str(rep.unregistered))
    rep = drift.check_text("表情集 EXP_CHR001_愤怒 已产出。", known)
    check("已登记的表情 → ok", rep.ok, str(rep.unregistered))
    rep = drift.check_text("表情集 EXP_CHR001_悲伤 未登记。", known)
    check("未登记的表情 → 报出", "EXP_CHR001_悲伤" in rep.unregistered)

    rep = drift.check_text("分镜表 SHT_S01_006 ｜ 视频 VID_SHT_S01_006 ｜ 音频 AUD_BGM_001。",
                           known)
    check("SHT_/VID_/AUD_ → **不判定**（进 foreign，不当未登记）",
          rep.ok and len(rep.foreign) == 3, str(rep.unregistered))
    check("外来前缀标注了归属模块",
          {o for _, o in rep.foreign} == {"03-分镜导演", "04-视频生成", "05-音乐音频"},
          str(rep.foreign))

    print()
    print("── ❌ 必须报出：一号两类型 ──")
    # ⚠️ 第一版这里写的是「遍历 issued 找同一 ID 两种类型」——
    #    那是 dict，一个 key 不可能有两种值 → **逻辑上永远返回空**。
    #    故改判「两处独立事实的对照」，测试也跟着改（否则测的是个不可能报错的检查器）。
    root4 = make_project(tmp / "p4", {"CHR_001": {"type": "character"}},
                         ["characters/CHR_001", "scenes/CHR_001"])
    bad = drift.check_conflicts(root4)
    check("同一 ID 落在两个类型目录 → 报出", len(bad) == 1, str(bad))

    root5 = make_project(tmp / "p5", {"CHR_002": {"type": "character"}},
                         ["characters/CHR_002"])
    (root5 / "assets" / "characters" / "CHR_002" / "latest.json").write_text(
        json.dumps({"id": "CHR_002", "type": "environment"}), encoding="utf-8")
    bad5 = drift.check_conflicts(root5)
    check("总表登记类型 ≠ 卡片实际类型 → 报出",
          any("CHR_002" in b for b in bad5), str(bad5))

    root6 = make_project(tmp / "p6", {"CHR_001": {"type": "character"}},
                         ["characters/CHR_001"])
    check("无冲突时返回空（**且这条不是空断言**：上面两条已证明它会报）",
          not drift.check_conflicts(root6))

    print()
    print("── ⚠️ 必须报出：两张单子不一致 ──")
    root2 = make_project(tmp / "p2", {"CHR_001": {"type": "character"},
                                      "CHR_009": {"type": "character"}},
                         ["characters/CHR_001", "characters/CHR_007"])
    _k2, gap2 = drift.load_registry(root2)
    check("登记了但无卡片 → 报出", any("CHR_009" in g for g in gap2), str(gap2))
    check("有卡片但未登记 → 报出", any("CHR_007" in g for g in gap2), str(gap2))

    print()
    print("── 全库扫描：孤儿资产（登记了但无人引用）──")
    root3 = make_project(tmp / "p3", {"CHR_001": {"type": "character"},
                                      "CHR_002": {"type": "character"}},
                         ["characters/CHR_001", "characters/CHR_002"])
    d = root3 / "output" / "prompts" / "CHR_001"
    d.mkdir(parents=True, exist_ok=True)
    (d / "v001.md").write_text("# CHR_001 佣兵\n\n引用：CHR_001\n", encoding="utf-8")
    rep3 = drift.scan_output(root3, drift.load_registry(root3)[0])
    check("CHR_001 被引用 → 不是孤儿", "CHR_001" not in rep3.orphans, str(rep3.orphans))
    check("CHR_002 无人引用 → 列为孤儿/未登记待查", "CHR_002" in rep3.orphans,
          str(rep3.orphans))

    print()
    print("── §六 风格锚点一致性（防全片画风漂移）──")
    auth = {"cinematic_quality": "controlled key light, soft fill",
            "quality_targets": "photorealistic / lifelike priority; ultra-high detail"}
    # ① 正常：纯文本形态（.md）
    md_ok = ("...\nCINEMATIC QUALITY (concrete, not just the word 'cinematic'): "
             "controlled key light, soft fill\n"
             "STYLE: x. Quality targets: photorealistic / lifelike priority; "
             "ultra-high detail.\n")
    rep = drift.check_anchors([("a.md", md_ok), ("b.md", md_ok)], auth)
    check("两条纯文本交付物锚点一致 → ok", rep.ok and rep.checked == 2,
          f"checked={rep.checked} dev={rep.deviated} inc={rep.inconsistent}")

    # ② ⭐ 回归用例：**JSON 形态**（换行是转义的 `\`+`n`，串尾是 `"`）
    #    这个形态我**连续踩了两次**：`[^\n]+` 不认转义换行 → 一路吞到行尾；
    #    只认 `\"` 又会把 JSON 的**结束引号**和逗号一起吃进来。
    #    故固化成用例，防再犯。
    json_ok = ('{"prompt_en": "...\\nCINEMATIC QUALITY (concrete, not just the word '
               "'cinematic'): controlled key light, soft fill\\nSTYLE: x. "
               'Quality targets: photorealistic / lifelike priority; ultra-high detail.\\n"}')
    a = drift.extract_anchor(json_ok)
    check("JSON 转义换行形态：光影锚点抓对（不多吃）",
          a.get("cinematic_quality") == auth["cinematic_quality"],
          repr(a.get("cinematic_quality")))
    check("JSON 转义换行形态：画质锚点抓对（不吞结束引号与逗号）",
          a.get("quality_targets") == auth["quality_targets"],
          repr(a.get("quality_targets")))
    check("JSON 形态与文本形态 → 判定一致（不误报）",
          drift.check_anchors([("a.json", json_ok), ("b.md", md_ok)], auth).ok)

    # ③ 必须报出：锚点被改动
    tampered = md_ok.replace("controlled key light, soft fill",
                             "controlled key light, **warm** fill")
    rep = drift.check_anchors([("a.md", md_ok), ("bad.md", tampered)], auth)
    check("锚点被改 → ❌ 报出（这就是画风漂移）",
          not rep.ok and any(s == "bad.md" for s, _, _, _ in rep.deviated),
          str(rep.deviated))

    # ④ 必须报出：交付物之间不一致（与权威也都不一致时以前者为准，这里用不设权威的情形）
    rep = drift.check_anchors([("a.md", md_ok), ("b.md", tampered)], {})
    check("交付物之间锚点不同 → ❌ 报出",
          not rep.ok and rep.inconsistent, str(rep.inconsistent))

    # ⑤ 未带锚点 → 列入 missing（⚠️不算 ❌，与"缺失 vs 漂移"区分开）
    rep = drift.check_anchors([("a.md", md_ok), ("n.md", "没有锚点的一段话")], auth)
    check("没带锚点的交付物 → 进 missing（不误报为漂移）",
          rep.missing == ["n.md"] and rep.ok, f"{rep.missing} ok={rep.ok}")

    print()
    print("── §六「锁定清单」：交付物里的 LOCK_* 必须属于 §一 ──")
    valid = {"LOCK_FACE", "LOCK_HAIR", "LOCK_COLOR"}
    check("合法的 LOCK_* → 不报",
          not drift.check_locks("锁定项 LOCK_FACE LOCK_HAIR", valid))
    check("`LOCK_CUT`（不在 §一）→ 报出",
          drift.check_locks("locked: LOCK_CUT", valid) == ["LOCK_CUT"], )
    # ⭐ 这条抓的正是本项目真实发生过的错：6 个 agent 曾硬编码
    #    ["CUT","LAYER_ORDER"] / ["STRUCTURE"] 当锁定项 —— 它们都**不是 LOCK_* 名**。
    check("`LOCK_STRUCTURE` / `LOCK_CUT`（历史上真实写过的错）→ 报出",
          set(drift.check_locks("LOCK_STRUCTURE, LOCK_CUT", valid))
          == {"LOCK_STRUCTURE", "LOCK_CUT"})
    check("非 LOCK_ 的大写词（CHR_001 / FACE / HAIR）→ **不误报**",
          not drift.check_locks("CHR_001 FACE HAIR BODY", valid))
    check("没给清单时不做判定（不误报）", not drift.check_locks("LOCK_ANY", set()))

    print()
    print("── ⚠️ 诚实说明：§六 另两项必须显式列为「未核验」 ──")
    txt = "\n".join(drift.UNCHECKED_NOTES)
    # 风格锚点**能核验**（按权威规则判定，不依赖那张表）；
    # 工作流侧那条错引用**已订正**，但仍须写清楚"权威位置在哪"，供人核对。
    check("写明风格锚点表的正确位置（VISUAL_BIBLE §4.8 + TURNAROUND §六）",
          "VISUAL_BIBLE.md` §4.8" in txt and "TURNAROUND-STANDARD.md` §六" in txt,
          txt[:150])
    check("写明这条引用曾**差一节**（§七 → §六）", "差一节" in txt)
    check("明确列出「不验 ID 的语义正确性」", "语义正确性" in txt)
    check("明确列出「不验风格本身好不好（艺术判断）」", "艺术判断" in txt)

    print()
    print("=" * 66)
    if FAIL:
        print(f"❌ 失败 {len(FAIL)} 项 / 共 {len(PASS) + len(FAIL)} 项：")
        for f in FAIL:
            print("   ·", f)
        return 1
    print(f"✅ 全部通过 —— {len(PASS)} 项（含**故意注入的漂移**，证明它真会报 ❌）")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
