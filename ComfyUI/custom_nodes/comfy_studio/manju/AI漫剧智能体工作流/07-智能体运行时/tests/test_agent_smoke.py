# -*- coding: utf-8 -*-
"""**六类资产冒烟测试** —— 每一类都真的走一遍创建路径。

═══════════════════════════════════════════════════════════════════
为什么必须有这个文件
═══════════════════════════════════════════════════════════════════
2026-09-24 实测踩到：接线「通用补全层」时我写成 `sd.name`
（`SceneDNA` **没有** `name` 字段，只有 `name_en`）→ **场景创建直接崩**
（AttributeError），却**逃过了那轮的全部测试** —— 因为当时新增的端到端用例
只覆盖了服装和道具，**没跑场景**。

这类失败形态值得单独防：
  · 它是**崩溃**（不是输出错），但因"没人跑到那条分支"而潜伏；
  · 六个 agent 是**平行分支**，改一处极易只测一处；
  · 项目此前也只有"跑一遍看到输出"的人工验证，没有覆盖到全部类型。

故本测试对**六类资产各跑一次真实的 `handle()` 路径**（不是只调 `complete()`），
断言：① 不抛异常；② 产出了资产卡；③ **英文 prompt 里 0 个中文字符**。

⚠️ 用**临时工作区**（`AgentConfig.root` 指向 tmp），不污染项目 `assets/`。

运行：`python tests/test_agent_smoke.py`
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent import AgentConfig, DramaAssetAgent     # noqa: E402

PASS, FAIL = [], []

CJK = lambda s: [c for c in (s or "") if "\u4e00" <= c <= "\u9fff"]  # noqa: E731

# (标签, 描述, 强制类型)  —— 用**表外题材**（民国）以同时覆盖通用性
CASES = [
    ("角色", "一个30岁的民国谍战女特工，穿旗袍，携带密码本", "character"),
    ("服装", "给女特工设计一套民国旗袍", "costume"),
    ("道具", "设计一个民国密码本", "prop"),
    ("场景", "民国上海洋行的大厅", "environment"),
    ("表情", "给 CHR_001 做一套表情集", "expression"),
    ("动作", "给 CHR_001 做一套动作集", "pose"),
]


def check(label: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(label)
    print(f"  {'✅' if ok else '❌'} {label}" + (f"   ← {detail}" if detail and not ok else ""))


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="_smoke_"))
    try:
        return _run(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run(tmp: Path) -> int:
    for sub in ("assets", "output", "config"):
        (tmp / sub).mkdir(parents=True, exist_ok=True)
    cfg = AgentConfig.load(Path(__file__).resolve().parent.parent)
    cfg.root = tmp
    ag = DramaAssetAgent(cfg)
    ag.cfg.generate = False

    print("── 六类资产各跑一次真实创建路径（表外题材：民国）──")
    ids: dict[str, str] = {}
    for label, text, atype in CASES:
        # 表情/动作依赖 owner：把上一步建的角色 ID 填进去
        t = text
        if "CHR_001" in t and ids.get("角色"):
            t = t.replace("CHR_001", ids["角色"])
        try:
            res = ag.handle(t, asset_type=atype, generate=False)
        except Exception as e:                                      # noqa: BLE001
            check(f"{label} 创建不抛异常", False, f"{type(e).__name__}: {e}")
            continue
        check(f"{label} 创建不抛异常", True)
        aid = res.get("asset_id", "")
        ids[label] = aid
        check(f"{label} 产出资产卡（{aid}）", bool(aid) and bool(res.get("card")),
              str(res.get("error", "")))
        en = res.get("prompt_en", "")
        bad = CJK(en)
        check(f"{label} 英文 prompt 无中文", not bad,
              f"{len(bad)} 个：{''.join(bad[:12])}")

    print()
    print("── 六类资产**各自**都真的落盘了 ──")
    for label, _t, atype in CASES:
        d = tmp / "assets" / {
            "character": "characters", "costume": "costumes", "prop": "props",
            "environment": "scenes", "expression": "expressions",
            "pose": "poses"}[atype]
        n = len(list(d.glob("*/latest.json"))) if d.is_dir() else 0
        check(f"{label} 落盘（{d.name}/）", n >= 1, f"{n} 个")

    print()
    print("── 指代消解按类型（库里同时有角色/道具/场景）──")
    try:
        res = ag.handle("把她的头发换成银白色", generate=False)
        ok = res.get("asset_id", "").startswith("CHR_")
        check("「她」命中**角色**而非场景/道具", ok, str(res.get("asset_id")))
    except Exception as e:                                          # noqa: BLE001
        check("改色路径不抛异常", False, f"{type(e).__name__}: {e}")

    print()
    print("=" * 66)
    if FAIL:
        print(f"❌ 失败 {len(FAIL)} 项 / 共 {len(PASS) + len(FAIL)} 项：")
        for f in FAIL:
            print("   ·", f)
        return 1
    print(f"✅ 全部通过 —— {len(PASS)} 项（六类资产 × 创建/落盘/英文纯度）")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
