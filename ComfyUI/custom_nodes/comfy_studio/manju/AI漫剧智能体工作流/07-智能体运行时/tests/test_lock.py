# -*- coding: utf-8 -*-
"""锁定系统与修改引擎（`LOCK-SYSTEM.md` §三「修改执行四步（强制）」）的测试。

═══════════════════════════════════════════════════════════════════
重点（沿用本项目铁律）
═══════════════════════════════════════════════════════════════════
**不是**"正常情况通过"，而是证明它**真的会报**：
改到 §四·补 A 的终身固定项（如**瞳色**）必须报；改可变项（如发色）**不得**误报。

另外钉住三条不变量：
  ① 代码里出现的 `LOCK_*` 名**必须**都在 §一 清单里（防再出现
     `["CUT","LAYER_ORDER"]` / `["建筑","门窗"]` 那类"不是锁定项的名字"）
  ② `locked` 与 `editable` **不得有交集**（曾出现 `locked == editable` 的语义反转）
  ③ CHANGELOG 的 `changed` / `unchanged` **必须完整**（模板 §项目管理 明文）

运行：`python tests/test_lock.py`
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import lock                        # noqa: E402
from src.rule_source import RuleSource      # noqa: E402

PASS, FAIL = [], []


def check(label: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(label)
    print(f"  {'✅' if ok else '❌'} {label}" + (f"   ← {detail}" if detail and not ok else ""))


class Card:
    """最小替身（只需 `locked` 字段）。"""

    def __init__(self, locked=None):
        self.locked = locked or []


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="_lock_test_"))
    try:
        return _run(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run(tmp: Path) -> int:
    r = RuleSource()

    print("── §一 可锁定资产清单（从工作流解析，不硬编码）──")
    names = lock.lock_names(r)
    check("解析出 13 项", len(names) == 13, str(len(names)))
    check("全部以 LOCK_ 开头", all(n.startswith("LOCK_") for n in names))
    check("含 LOCK_FACE / LOCK_HAIR / LOCK_COLOR",
          {"LOCK_FACE", "LOCK_HAIR", "LOCK_COLOR"} <= set(names))

    print()
    print("── §二 自然语言 → 锁定映射（17 行，两种表达形式都要认）──")
    rows = r.nl_lock_map
    check("解析出 §二 的映射表", len(rows) >= 15, str(len(rows)))
    d = lock.parse_directive("人物不变，只换衣服", r)
    check("「人物不变，只换衣服」→ 5 项，只有 COSTUME=MODIFY",
          len(d) == 5 and d.get("COSTUME") == "MODIFY"
          and all(v == "LOCK" for k, v in d.items() if k != "COSTUME"), str(d))
    d = lock.parse_directive("只换发型", r)
    check("「只换发型」→ ALL=LOCK 展开为 13 项，HAIR=MODIFY",
          len(d) == 13 and d.get("HAIR") == "MODIFY", str(len(d)))
    d = lock.parse_directive("全部保持不变", r)
    check("「全部保持不变（§43）」→ 9 项全 LOCK（**第二种表达形式**，无 `=`）",
          len(d) == 9 and all(v == "LOCK" for v in d.values()), str(d))

    print()
    print("── §四·补 A / B：默认锁定集与可变集（权威推导）──")
    locked = lock.default_locks(r, "character")
    editable = lock.default_editable(r, "character")
    check("角色默认 locked = §四·补 A（含瞳色所属的 FACE）",
          set(locked) == {"LOCK_FACE", "LOCK_CHARACTER", "LOCK_EXPRESSION"}, str(locked))
    check("角色默认 editable = §四·补 B（含发色所属的 HAIR）",
          set(editable) == {"LOCK_HAIR", "LOCK_BODY", "LOCK_COSTUME", "LOCK_PROP"},
          str(editable))
    check("⭐ locked 与 editable **无交集**（曾出现 locked==editable 的语义反转）",
          not (set(locked) & set(editable)), str(set(locked) & set(editable)))
    check("HAIR **不在** locked（§四·补 B 明文「发色变化/发型」可变）",
          "LOCK_HAIR" not in locked)
    check("非角色类不臆造（道具/服装类返回空）",
          lock.default_locks(r, "prop") == [] and lock.default_editable(r, "scene") == [])

    print()
    print("── 自检：代码里的 LOCK_* 名必须在 §一 清单里 ──")
    check("FIELD_TO_LOCK 的译名全部合法", not lock.validate_field_map(r),
          str(lock.validate_field_map(r)))
    check("§四·补 A 的译名全部合法", not lock.validate_lifelong_map(r),
          str(lock.validate_lifelong_map(r)))
    short = lock.SHORT_NAMES(r)
    bad = {v for v in lock.FIELD_TO_LOCK.values() if v not in short}
    check("没有 `CUT`/`LAYER_ORDER`/`STRUCTURE`/`建筑` 那类**不是锁定项的名字**",
          not bad, str(bad))

    print()
    print("── ❌ 必须报出：改到 §四·补 A 的终身固定项 ──")
    c = lock.lifelong_conflicts(["eye_color"])
    check("改**瞳色** → 报出（原文：瞳色「不可变」）",
          bool(c) and "瞳色" in c[0], str(c))
    check("提示语引用「重新设计角色」与「递增主版本号」",
          bool(c) and "重新设计角色" in c[0] and "递增主版本号" in c[0])
    check("改五官轮廓（lips）→ 报出", bool(lock.lifelong_conflicts(["lips"])))
    check("改标志性识别点（permanent_marks）→ 报出",
          bool(lock.lifelong_conflicts(["permanent_marks"])))

    print()
    print("── ✅ 不该误报：改 §四·补 B 的可变项 ──")
    check("改**发色** → 不报（§四·补 B 明文可变）",
          not lock.lifelong_conflicts(["hair_color"]))
    check("改服装 → 不报", not lock.lifelong_conflicts(["clothing"]))
    check("改年龄段/世界观 → 不报",
          not lock.lifelong_conflicts(["age", "world"]))

    print()
    print("── §三 STEP 2：卡片锁定 vs 本次变更 ──")
    # 用户明确要求改锁定项 → 不算冲突（只记说明）
    rep = lock.detect_conflicts(Card(["LOCK_HAIR"]), ["hair_color"], r,
                                {"HAIR": "MODIFY"})
    check("指令明确 MODIFY 锁定项 → **不算冲突**，只记说明",
          not rep.conflicts and rep.notes, f"c={rep.conflicts} n={rep.notes}")
    # 卡片上有 LOCK_HAIR 但指令没提要改它 → 提示（不是 error，原文说"提示用户"）
    rep = lock.detect_conflicts(Card(["LOCK_HAIR"]), ["hair_color"], r, {})
    check("指令未提却改锁定项 → 记入提示", bool(rep.notes), str(rep.notes))
    # 改终身固定项 → 必报
    rep = lock.detect_conflicts(Card(), ["eye_color"], r, {})
    check("改瞳色 → conflicts 非空（§四·补 A）",
          bool(rep.conflicts), str(rep.conflicts))

    print()
    print("── §三 STEP 4：CHANGELOG（模板字段严格对齐）──")
    root = tmp / "proj"
    root.mkdir(parents=True, exist_ok=True)
    p = lock.append_entry(root, asset="CHR_001", version="v001",
                          changed=["初次生成"], unchanged=[],
                          reason="项目启动")
    lock.append_entry(root, asset="CHR_001", version="v002",
                      changed=["HAIR"], unchanged=["FACE", "BODY", "COLOR"],
                      reason="用户要求「只换发型」")
    txt = p.read_text(encoding="utf-8")
    check("落盘路径为 output/CHANGELOG.yaml",
          p == root / "output" / "CHANGELOG.yaml", str(p))
    check("含模板的 5 个字段", all(k in txt for k in
                                  ("version:", "asset:", "changed:",
                                   "unchanged:", "reason:")))
    check("`unchanged` 为空时**也显式写出 `[]`**（不得省略）",
          "unchanged: []" in txt, txt[:200])
    entries = lock.read_entries(root)
    check("读回 2 条", len(entries) == 2, str(len(entries)))
    check("字段解析正确（供「恢复上一版」用）",
          entries[1]["version"] == "v002" and entries[1]["changed"] == ["HAIR"]
          and entries[1]["unchanged"] == ["FACE", "BODY", "COLOR"], str(entries[1]))
    check("首次记录按模板写法（changed=['初次生成']）",
          entries[0]["changed"] == ["初次生成"] and entries[0]["unchanged"] == [])

    print()
    print("── §二 里的**指令语义**（非 LOCK 映射，不能当解析失败丢掉）──")
    check("「重新生成」→ resample（§44）", lock.command_kind("重新生成这张图") == "resample")
    check("「恢复上一版」→ rollback_prev（§33）",
          lock.command_kind("恢复上一版") == "rollback_prev")
    check("「恢复原版」→ rollback_first", lock.command_kind("恢复原版") == "rollback_first")
    check("「取消这次修改」→ rollback_cancel",
          lock.command_kind("取消这次修改") == "rollback_cancel")
    check("普通创建语句不误判为命令", lock.command_kind("一个废土女佣兵") == "")

    print()
    print("=" * 66)
    if FAIL:
        print(f"❌ 失败 {len(FAIL)} 项 / 共 {len(PASS) + len(FAIL)} 项：")
        for f in FAIL:
            print("   ·", f)
        return 1
    print(f"✅ 全部通过 —— {len(PASS)} 项（含**必须报/不得误报**两类注入用例）")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
