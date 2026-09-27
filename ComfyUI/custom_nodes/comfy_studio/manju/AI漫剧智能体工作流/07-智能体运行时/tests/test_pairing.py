# -*- coding: utf-8 -*-
"""词表「中英成对」守卫（角色 / 服装 / 道具 / 场景 / 动作）。

═══════════════════════════════════════════════════════════════════
为什么值得单独测
═══════════════════════════════════════════════════════════════════
中文进 `prompt_cn`、英文伴生进 `prompt_en`。**漏一个英文伴生不会报错**，
症状是英文 prompt 里夹一堆中文 —— 图照样出，只是质量悄悄变差。
`costume_agent.py` 的注释写着「只给中文会让英文 prompt 夹中文（实测踩到）」，
`pose_agent.py` 更直白：「缺了它，`ITEMS` / `LAYOUT` 两行会往英文 prompt 里塞进
400+ 个汉字」。这条守卫就是防它再犯。

本项目里同时存在三种写法，三种都认：

* 同一行里的兄弟键 `silhouette` / `silhouette_en`   —— costume / prop
* 同一行里的兄弟键 `hair_cn` / `hair_en`             —— character
* 两张表按名字对齐 `BASELINE_18` ↔ `BASELINE_18_EN` —— scene / pose

⚠️ 本文件**先断言"确实检查到了足够多的条目"再断言成对**：表被改名、被清空、
或者清单写错时，只查成对的测试会**静静地全绿** —— 本项目最忌讳的失败形态
（换台机器就静默跳过；守卫通过 ≠ 守卫在跑）。

运行：`python tests/test_pairing.py`
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import (  # noqa: E402
    character_agent,
    costume_agent,
    pose_agent,
    prop_agent,
    scene_agent,
)

PASS, FAIL = [], []


def check(label: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(label)
    print(f"  {'✅' if ok else '❌'} {label}" + (f"   ← {detail}" if detail and not ok else ""))


#: 形态一：表里的每一行自带中英兄弟键。改成别的名字时第 ① 组会先报"没有可检查的行"。
PAIRED_TABLES: tuple[tuple[str, Any], ...] = (
    ("costume_agent.COSTUME_PRESETS", costume_agent.COSTUME_PRESETS),
    ("costume_agent.DEFAULT_COSTUME", costume_agent.DEFAULT_COSTUME),
    ("prop_agent.PROP_PRESETS", prop_agent.PROP_PRESETS),
    ("prop_agent.DEFAULT_PROP", prop_agent.DEFAULT_PROP),
    ("character_agent.WORLD_PRESETS", character_agent.WORLD_PRESETS),
    ("character_agent.GENERIC_PRESET", character_agent.GENERIC_PRESET),
)

#: 形态三：中文清单与英文映射表按名字对齐。
ALIGNED_TABLES: tuple[tuple[str, list[str], Any], ...] = (
    (
        "scene_agent.SCENE_PRESETS 的场景名（含默认场景）",
        [str(preset["name"]) for preset in scene_agent.SCENE_PRESETS]
        + [str(scene_agent.DEFAULT_SCENE["name"])],
        scene_agent.SCENE_EN,
    ),
    (
        "pose_agent.BASELINE_18 的 18 个动作",
        [name for name, *_ in pose_agent.BASELINE_18],
        pose_agent.BASELINE_18_EN,
    ),
)


#: `cn` 里有、`en` 里**故意**没有的字段：它们的英文走另一张表。
#: 证据：`scene_agent.py:288` 的注释（"style 只在各预设的 cn 里有"）+
#: `:391` 从 `SCENE_EN[name][1]` 回填 `architectural_style_en`。
#: 豁免不等于放任 —— 下面第 ④ 组仍要断言这个字段确实能从 `SCENE_EN` 拿到英文。
CN_ONLY_FIELDS = frozenset({"style"})


def rows(table: Any) -> Iterator[tuple[str, dict]]:
    """把一张表摊成 (行名, 行)。

    两种形态都要认：``dict[str, dict]``（每个值是一行，如 ``COSTUME_PRESETS``）与
    单行表（整张表就是一行，如 ``DEFAULT_COSTUME``）；``list[dict]`` 按下标当行名。
    """
    if isinstance(table, dict):
        if table and all(isinstance(value, dict) for value in table.values()):
            yield from ((str(key), value) for key, value in table.items())
            return
        yield "<单行表>", table
        return
    if isinstance(table, list):
        for index, value in enumerate(table):
            if isinstance(value, dict):
                yield f"[{index}]", value


def problems_in(row: dict) -> list[str]:
    """这一行里所有不成对的字段（缺英文伴生 / 英文孤儿）。"""
    problems: list[str] = []
    for key in row:
        if key.endswith("_cn"):
            base = key[:-3]
            if f"{base}_en" not in row:
                problems.append(f"{key} 缺英文伴生 {base}_en")
        elif key.endswith("_en"):
            base = key[:-3]
            if base not in row and f"{base}_cn" not in row:
                problems.append(f"{key} 是孤儿（没有 {base} / {base}_cn）")
        elif f"{key}_en" not in row:
            problems.append(f"{key} 缺英文伴生 {key}_en")
    return problems


def alignment_problems(names: list[str], table: Any) -> list[str]:
    """清单里有名字但英文表没有、或英文表里有孤儿键。"""
    problems = [f"{name} 在英文表里没有（或为空）" for name in names if not str(table.get(name, "")).strip()]
    problems += [f"{key} 是孤儿（中文清单里没有）" for key in table if key not in names]
    return problems


def main() -> int:
    print("── ① 守卫自己不许空转（表被改名/清空时必须先报出来）──")
    total_rows = 0
    total_fields = 0
    for label, table in PAIRED_TABLES:
        got = list(rows(table))
        check(f"{label} 有可检查的行", bool(got), f"{len(got)} 行")
        check(f"{label} 的行不为空", all(len(row) > 0 for _, row in got))
        total_rows += len(got)
        total_fields += sum(len(row) for _, row in got)
    check(
        f"形态一合计检查到足够多的字段（> 150，实测 {total_fields}）",
        total_fields > 150,
        f"{total_fields} 个字段 / {total_rows} 行",
    )
    for label, names, table in ALIGNED_TABLES:
        check(f"{label} 清单非空（{len(names)} 个）", len(names) > 5, f"{len(names)} 个")
        check(f"{label} 英文表非空（{len(table)} 键）", len(table) > 5, f"{len(table)} 键")

    print()
    print("── ② 表里每一行的每个字段都中英成对 ──")
    for label, table in PAIRED_TABLES:
        for name, row in rows(table):
            found = problems_in(row)
            check(f"{label}.{name}", not found, "；".join(found[:4]))

    print()
    print("── ③ 中文清单 ↔ 英文映射表：两边名字必须一一对上 ──")
    for label, names, table in ALIGNED_TABLES:
        found = alignment_problems(list(names), table)
        check(f"{label}（{len(names)} 个名字 / 英文表 {len(table)} 键）", not found, "；".join(found[:4]))

    baseline_names = [name for name, *_ in pose_agent.BASELINE_18]
    check(
        "pose_agent.SUBSET_6 都出自 BASELINE_18",
        all(name in baseline_names for name in pose_agent.SUBSET_6),
        str([name for name in pose_agent.SUBSET_6 if name not in baseline_names]),
    )

    print()
    print("── ④ 场景预设的 cn / en 两组字段必须同键 ──")
    for index, preset in enumerate(scene_agent.SCENE_PRESETS):
        name = str(preset.get("name", f"[{index}]"))
        cn, en = preset.get("cn"), preset.get("en")
        if not (isinstance(cn, dict) and isinstance(en, dict)):
            check(
                f"scene_agent.SCENE_PRESETS.{name} 同时有 cn 与 en",
                False,
                f"cn={type(cn).__name__} en={type(en).__name__}",
            )
            continue
        found = (
            [f"cn 有 {key} 但 en 没有" for key in cn if key not in en and key not in CN_ONLY_FIELDS]
            + [f"en 多出 {key}" for key in en if key not in cn]
            + [f"{key} 的英文是空的" for key, value in en.items() if not str(value).strip()]
            + [f"{key} 的中文是空的" for key, value in cn.items() if not str(value).strip()]
        )
        check(f"scene_agent.SCENE_PRESETS.{name}（{len(cn)} 个字段）", not found, "；".join(found[:4]))
        # 豁免掉的字段不能真的没人管：英文风格必须能从 SCENE_EN 拿到（否则英文 prompt 里会夹中文）。
        for key in sorted(CN_ONLY_FIELDS & set(cn)):
            style_en = scene_agent.SCENE_EN.get(name, ("", ""))[1]
            check(
                f"scene_agent.SCENE_PRESETS.{name}.{key} 的英文由 SCENE_EN 兜住",
                bool(str(style_en).strip()),
                "SCENE_EN 里没有对应的英文风格",
            )

    print()
    print("── ⑤ 规则自检：不合规的行必须被报出来（防规则失效）──")
    check(
        "缺英文会被报出来",
        any("only_cn" in p for p in problems_in({"only_cn": "只有中文", "ok": "中", "ok_en": "en"})),
        str(problems_in({"only_cn": "只有中文", "ok": "中", "ok_en": "en"})),
    )
    check(
        "英文孤儿会被报出来",
        any("orphan_en" in p for p in problems_in({"orphan_en": "x"})),
        str(problems_in({"orphan_en": "x"})),
    )
    check("合规的行不报", problems_in({"a": "中", "a_en": "en"}) == [])
    check(
        "`_cn`/`_en` 写法也认",
        problems_in({"a_cn": "中", "a_en": "en"}) == []
        and problems_in({"a_cn": "中"}) == ["a_cn 缺英文伴生 a_en"],
    )
    check(
        "映射表缺名字会被报出来",
        alignment_problems(["甲", "乙"], {"甲": "jia"}) == ["乙 在英文表里没有（或为空）"]
        and alignment_problems(["甲"], {"甲": "jia", "丙": "bing"}) == ["丙 是孤儿（中文清单里没有）"],
    )

    print()
    print("=" * 66)
    if FAIL:
        print(f"❌ 失败 {len(FAIL)} 项 / 共 {len(PASS) + len(FAIL)} 项：")
        for item in FAIL:
            print("   ·", item)
        return 1
    print(f"✅ 全部通过 —— {len(PASS)} 项")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
