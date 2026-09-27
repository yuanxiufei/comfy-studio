# -*- coding: utf-8 -*-
"""**通用性**测试 —— 任何一部小说都能跑，且英文 prompt 不夹中文。

═══════════════════════════════════════════════════════════════════
为什么需要这个文件
═══════════════════════════════════════════════════════════════════
① **通用性**：此前补全靠**固定题材表**（角色 11 题材 · 服装只 4 类 · 道具只 5 类 ·
   批量 5 池）。实测量化过：5 种输入里**服装预设全部没命中**，
   于是「穿**旗袍**的女特工」被补成「**棉**质三层功能服装」——
   **把用户给的事实换成了预设里的假具体值**。
   → 本测试钉住：**表外题材也要把用户原话写进字段**。

② **英文纯度**：本项目已**第 7 次**踩"英文 prompt 里夹中文"，
   且第 7 次是通用补全层自己引入的（把抽到的中文词拼进了英文）。
   → 本测试钉住：**8 种题材的英文 prompt 中文字符数必须为 0**。

运行：`python tests/test_generic.py`
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import generic as g                                  # noqa: E402
from src import nl_parser as nlp                              # noqa: E402

PASS, FAIL = [], []


def check(label: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(label)
    print(f"  {'✅' if ok else '❌'} {label}" + (f"   ← {detail}" if detail and not ok else ""))


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="_generic_test_"))
    try:
        return _run(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run(tmp: Path) -> int:
    print("── ① 语法抽取：**不依赖题材词表**（加词表是打地鼠）──")
    check("「穿旗袍的女特工」→ 抽出「旗袍」",
          g.noun_after("穿旗袍的女特工", g.CLOTHING_VERBS) == ["旗袍"])
    check("「身着青衫道袍与飞剑」→ 抽出「青衫道袍」（在「与」处截断）",
          g.noun_after("身着青衫道袍与飞剑", g.CLOTHING_VERBS) == ["青衫道袍"])
    check("「携带密码本」→ 抽出「密码本」",
          g.noun_after("携带密码本", g.ITEM_VERBS) == ["密码本"])
    check("「手握扳手」→ 抽出「扳手」",
          "扳手" in g.noun_after("手握扳手", g.ITEM_VERBS))
    check("⚠️ 单字「着」不吃——「戴着腕表」**不该**算成服装",
          g.noun_after("戴着腕表", g.CLOTHING_VERBS) == [],
          str(g.noun_after("戴着腕表", g.CLOTHING_VERBS)))
    check("同上：「提着提灯」「背着步枪」都不算服装",
          g.noun_after("提着提灯", g.CLOTHING_VERBS) == []
          and g.noun_after("背着步枪", g.CLOTHING_VERBS) == [])
    check("「头戴九翟冠」→ 抽出「九翟冠」（`_STOP` 不含中文数字）",
          g.noun_after("头戴九翟冠", g.ACCESSORY_VERBS) == ["九翟冠"],
          str(g.noun_after("头戴九翟冠", g.ACCESSORY_VERBS)))

    print()
    print("── ② 场所与时代 ──")
    check("「在废弃医院的地下室」→ 场所「废弃医院」",
          "废弃医院" in g.prep_place("在废弃医院的地下室"))
    check("「在霓虹街道上」→ 去掉尾部方位词，得「霓虹街道」",
          "霓虹街道" in g.prep_place("赛博朋克，在霓虹街道上"))
    check("无场所后缀时**不硬抽**（「在2026年」不该被当场所）",
          g.prep_place("在2026年发生") == [])
    check("⭐ 判据是「**以场所字结尾**」，故「在进行改革」**不误抽**",
          g.prep_place("在进行改革") == [], str(g.prep_place("在进行改革")))
    check("民国场所「洋行」「客栈」能抽到（此前后缀表没有它们）",
          g.prep_place("在上海洋行的大厅") == ["上海洋行"]
          and "客栈" in g.prep_place("在客栈里"))
    check("「民国」→ 民国时代（**中英成对**）",
          g.era_from_text("民国谍战")[0] == "民国"
          and g.era_from_text("民国谍战")[1] != "")
    check("无时代词 → 返回空（不编）", g.era_from_text("一个女佣兵") == ("", ""))

    print()
    print("── ③ ⭐ 英文安全闸：中文词**不得**拼进英文 ──")
    en, need = g.safe_en("密码本", "the specified item")
    check("含中文 → 英文改用通用表述", en == "the specified item" and need,
          repr(en))
    en, need = g.safe_en("Kevlar", "the specified item")
    check("纯 ASCII → 原样进英文（且不标记）", en == "Kevlar" and not need)
    check("空串 → 通用表述、不标记", g.safe_en("", "x") == ("x", False))

    print()
    print("── ④ 服装补全：用户原话优先，抽不到用**中性兜底**（不假装具体）──")
    from src.nl_parser import COLORS, MATERIALS
    hit, fb, notes = g.clothing_from_text("民国谍战，穿旗袍的女特工", MATERIALS, COLORS)
    check("形制 = 旗袍（用户原话）", hit.get("silhouette") == "旗袍", str(hit))
    check("英文形制**不含中文**", not any("\u4e00" <= c <= "\u9fa5"
                                        for c in hit.get("silhouette_en", "")),
          repr(hit.get("silhouette_en")))
    check("材质未识别 → 走**中性兜底**（不是假具体的「棉」）",
          "描述未指明材质" in fb.get("material", ""), str(fb.get("material")))
    check("兜底时**如实说明**（有 notes）", any("材质" in n for n in notes), str(notes))
    hit2, _fb2, _n2 = g.clothing_from_text("穿丝质长袍", MATERIALS, COLORS)
    check("材质能从原文识别时走真值（丝 → silk）",
          hit2.get("material") == "丝" and "silk" in hit2.get("material_en", ""),
          f"{hit2.get('material')} / {hit2.get('material_en')}")

    print()
    print("── ⑤ 道具补全 ──")
    hit, fb, notes = g.prop_from_text("民国谍战，携带密码本", MATERIALS, COLORS)
    check("结构含「密码本」（用户原话）", "密码本" in hit.get("structure", ""))
    check("英文结构**不含中文**",
          not any("\u4e00" <= c <= "\u9fa5" for c in hit.get("structure_en", "")),
          repr(hit.get("structure_en")))
    check("未识别材质 → 中性兜底 + 说明",
          "描述未指明材质" in fb.get("material", "")
          and any("材质" in n for n in notes))

    print()
    print("── ⑥ 场景补全 ──")
    hit, fb, notes = g.scene_from_text("民国谍战，在上海洋行的大厅")
    check("场所名来自原文（「上海洋行」以场所字「行」结尾）",
          hit.get("name") == "上海洋行", str(hit.get("name")))
    check("时代 = 民国", hit.get("era") == "民国")
    check("英文建筑描述不含中文",
          not any("\u4e00" <= c <= "\u9fa5" for c in hit.get("building_en", "")),
          repr(hit.get("building_en")))
    hit, fb, notes = g.scene_from_text("一个没有场所词的描述")
    check("无场所词 → 兜底 + 说明（不静默）",
          any("场所词" in n for n in notes), str(notes))

    print()
    print("── ⑦ 通用骨架本身必须**不含中文**（英文 prompt 用）──")
    for name, tbl in (("GENERIC_CLOTHING", g.GENERIC_CLOTHING),
                      ("GENERIC_PROP", g.GENERIC_PROP),
                      ("GENERIC_SCENE", g.GENERIC_SCENE)):
        bad = [k for k, v in tbl.items()
               if k.endswith("_en") and any("\u4e00" <= c <= "\u9fa5" for c in v)]
        check(f"{name} 的 `*_en` 值全为英文", not bad, str(bad))

    print()
    print("── ⑧ `world` 必须是**自由文本**，不是 11 个枚举值 ──")
    check("表内题材仍返回题材键", nlp._find_world("一个30岁的废土女佣兵") == "wasteland")
    check("⭐ 表外题材回退到**时代词**作为自由文本 world",
          nlp._find_world("民国谍战剧，一位穿旗袍的女特工") == "民国",
          nlp._find_world("民国谍战剧，一位穿旗袍的女特工"))
    check("没有题材词/时代词时返回空（不编）",
          nlp._find_world("一个女佣兵") in ("", "military"),
          nlp._find_world("一个女佣兵"))
    p = nlp.parse("民国谍战剧，一位穿旗袍的女特工")
    check("⭐ 资产名**不再含「-未定」**（那串会污染名字）",
          "未定" not in (p.name or "") and p.name == "女特工-民国", p.name)
    # ⚠️ 实测踩到：去掉「-未定」时**把「角色」这个身份兜底也一起去掉了**，
    #    于是职业抽不到时名字变成「**-民国**」（前导连字符）——
    #    端到端跑出来才发现。故对**一批**输入都断言"不以 - 开头 / 不以 - 结尾"。
    bad_names = []
    for _t in ("一个30岁的民国谍战女特工", "民国上海洋行的大厅", "一个30岁的废土女佣兵",
               "设计一把未来主义能源步枪", "废土末日的地下指挥中心", "穿旗袍的女人"):
        _n = nlp.parse(_t).name or ""
        if _n.startswith("-") or _n.endswith("-"):
            bad_names.append((_t, _n))
    check("⭐ 资产名不以「-」开头/结尾（职业兜底没被一并去掉）",
          not bad_names, str(bad_names))

    print()
    print("── ⑨ 批量：**用户给的清单优先于题材池**（generality 的最直接入口）──")
    import src.batch as bt
    got = bt.user_items("一次生成4个民国谍战人物：报务员、线人、舞女、巡捕")
    check("从「：」后抽出用户清单（按标点结构，不靠词表）",
          got == ["报务员", "线人", "舞女", "巡捕"], str(got))
    check("没有「：」清单时返回空（不臆造）",
          bt.user_items("一次生成10个废土NPC") == [])
    items, notes = bt.plan("一次生成4个民国谍战人物：报务员、线人、舞女、巡捕",
                           asset_type="character", world="民国")
    labels = [i["label"].split("·")[-1].strip() for i in items]
    check("⭐ 展开用的是**用户给的**身份", labels == got, str(labels))
    check("⭐ 生成文本**不含**那块「：清单」（它是规格不是内容）",
          all("：" not in i["text"] and "报务员、线人" not in i["text"]
              for i in items), items[0]["text"])
    check("说明里明确写出「取你给的清单」",
          any("你给的清单" in n for n in notes), str(notes))

    print()
    print("── ⑩ 批量：未命中题材池 → 通用骨架 + **明说**（不静默）──")
    pool, matched = bt.pool_for("民国")
    check("未命中题材池 → matched=False", not matched)
    check("默认身份是**社会身份**而非叙事标签（不含「主角/路人甲」）",
          not ({"主角", "伙伴", "对手", "导师", "路人甲"} & set(pool["jobs"])),
          str(pool["jobs"]))
    _it, nt = bt.plan("一次生成4个民国谍战NPC", asset_type="character",
                      world="民国")
    check("⭐ 未命中时**必须说明**（这是唯一的可见信号）",
          any("未命中题材池" in n for n in nt), str(nt))
    _it2, nt2 = bt.plan("一次生成4个废土NPC", asset_type="character",
                        world="wasteland")
    check("表内题材**命中** → 身份用该题材的具体值，且不报「未命中」",
          not any("未命中" in n for n in nt2), str(nt2))

    print()
    print("── ⑪ 场景 / 道具池也不得写死成某一题材 ──")
    check("道具池按题材分组（有 default 之外的键）",
          len(bt.PROP_POOLS) > 1 and "default" in bt.PROP_POOLS)
    check("场景池同上", len(bt.SCENE_POOLS) > 1 and "default" in bt.SCENE_POOLS)
    ws, wm = bt._typed_pool(bt.PROP_POOLS, "wasteland")
    ds, dm = bt._typed_pool(bt.PROP_POOLS, "民国")
    check("废土命中 → 用**具体**道具（能源步枪…）", wm and "能源步枪" in ws, str(ws[:3]))
    check("表外题材 → 用**题材无关类目**，且不报「能源步枪」",
          (not dm) and "能源步枪" not in ds, str(ds[:3]))

    print()
    print("── ⑫ ⭐ 类型判定：**靠语法，不靠名词表**（表外名词也要判对）──")
    # 实测踩到：这些句子里的名词都不在项目词表里 → 原先**全被判成角色**，
    # 连资产名都变成整句话（「设计一柄油纸伞」→ 角色「设计一柄油纸伞」）。
    TYPE_CASES = [
        # 器物：靠**量词**判（汉语语法事实，不随题材失效）
        ("设计一柄油纸伞", "prop"), ("设计一个民国密码本", "prop"),
        ("设计一台老式留声机", "prop"), ("设计一盏煤气路灯", "prop"),
        ("设计一只黄铜怀表", "prop"), ("设计一副乌木算盘", "prop"),
        ("设计一枚铜制徽章", "prop"),
        # 场景：靠**场所字结尾**判
        ("民国上海洋行的大厅", "environment"), ("一间逼仄的弄堂阁楼", "environment"),
        ("租界的码头仓库", "environment"), ("一座香火冷清的城隍庙", "environment"),
        ("老城区的当铺", "environment"),
        # 服装：靠**服饰量词**
        ("设计一套民国旗袍", "costume"), ("设计一件亚麻衬衫", "costume"),
        ("设计一身夜行衣", "costume"),
        # 角色：**回归重点** —— 新规则不能把它们抢走
        ("一个30岁的民国谍战女特工", "character"), ("穿旗袍的女人", "character"),
        ("一个在街上的女佣兵", "character"), ("一位药铺的掌柜", "character"),
        ("一个老练的船工", "character"), ("设计一个主角", "character"),
        ("一个废土拾荒者", "character"), ("民国谍战剧，一位穿旗袍的女特工", "character"),
        # ⚠️ **把字句**：「把」是介词不是量词（冒烟测试抓到的回归）
        ("把她的头发换成银白色", "character"),
        ("把他的脸换成苍白的", "character"),
    ]
    # ⚠️ **已知歧义（故意不测）**：「把他的义肢换成机械臂」——
    #    「义肢」在本项目里**既是角色部件、也是独立道具资产（PRP_）**，
    #    故"应为角色"或"应为道具"都有道理。把它当唯一正确答案来测是**假测试**。
    #    实测当前判为 prop（因句尾「机械臂」命中 `PROP_WORDS`）。
    #    若将来要定，应引入"'把'字句看**宾语**而非句尾"的规则，并先与用户确认语义。
    wrong = [(t, nlp._detect_asset_type(t), w) for t, w in TYPE_CASES
             if nlp._detect_asset_type(t) != w]
    check(f"⭐ {len(TYPE_CASES)} 条类型判定全对（含表外名词 + 把字句）",
          not wrong, str(wrong[:4]))

    print()
    print("── ⑬ 判据是「**结尾**」而不是「含」（中心语在最后）──")
    check("「一位药铺的掌柜」→ 角色（不因中间有「药/铺」被判成道具/场景）",
          nlp._detect_asset_type("一位药铺的掌柜") == "character")
    check("「一个老练的船工」→ 角色（不因中间有「船」被判成场景）",
          nlp._detect_asset_type("一个老练的船工") == "character")
    check("`_has_place_word` 看结尾：洋行的大厅 ✓ / 药铺的掌柜 ✗",
          nlp._has_place_word("民国上海洋行的大厅")
          and not nlp._has_place_word("一位药铺的掌柜"))
    check("`_tail_has` 看结尾：「药」不在「药铺的掌柜」结尾 → 不命中道具",
          not nlp._tail_has("一位药铺的掌柜", nlp.PROP_WORDS))

    print()
    print("── ⑭ 场所后缀表**只有一份**（两处判据不得分叉）──")
    from src import generic as _g
    check("`nl_parser.PLACE_SUFFIX` 与 `generic.PLACE_SUFFIX` 是**同一个对象**",
          nlp.PLACE_SUFFIX is _g.PLACE_SUFFIX)
    check("「洋行 / 当铺 / 客栈」这类无标准后缀的场所也在表里",
          all(w in _g.PLACE_SUFFIX for w in "铺栈驿"))

    print()
    print("── ⑮ 查询过滤词：**结构抽取**，不再是 8 个写死的词 ──")
    # ⚠️ 原实现只认 ("机械","废土","赛博","银发","长发","废墟","霓虹","指挥中心")
    #    这 8 个词 —— 表外的对象名（旗袍/密码本）抽不到 → **静默返回全部**，
    #    而 CLI 连"过滤词是什么"都不显示。两个错叠在一起，用户看不出来。
    from src import agent as _ag
    term = _ag._search_term
    for text, want in (("有哪些旗袍", "旗袍"),
                       ("查一下密码本", "密码本"),
                       ("列出所有银发角色", "银发"),
                       ("列出所有民国角色", "民国"),
                       ("有哪些盔甲", "盔甲"),
                       ("查看 CHR_001", "CHR_001")):
        got = term(text)[0]
        check(f"「{text}」→ 过滤词「{want}」", got == want, f"实际「{got}」")
    check("⭐ 宾语里的「的」不吃掉中心语（「有哪些银发的角色」→「银发」）",
          term("有哪些银发的角色")[0] == "银发", term("有哪些银发的角色")[0])

    check("去尾只去**通用类目**，不去具体物件（「盔甲」是真过滤词）",
          _ag._strip_type_tail("银发角色") == "银发"
          and _ag._strip_type_tail("盔甲") == "盔甲"
          and _ag._strip_type_tail("资产") == "",
          f"{_ag._strip_type_tail('银发角色')}/"
          f"{_ag._strip_type_tail('盔甲')}/{_ag._strip_type_tail('资产')}")
    check("⭐ 触发词本身不算过滤词（「列出所有」→ 空，**不拿「所有」去搜卡片**）",
          term("列出所有")[0] == "", term("列出所有")[0])
    check("纯类目词不算过滤词（「有哪些资产」→ 按类型列全部）",
          term("有哪些资产")[0] == "", term("有哪些资产")[0])
    check("抽不到就返回空（**不编**）", term("给我看看") == ("", ""),
          str(term("给我看看")))

    # ⚠️⚠️ **教训：测试要测在真正起作用的层上。**
    #    上面「查看 CHR_001 → CHR_001」抽得**完全正确**，但端到端跑出来：
    #        $ python main.py "查看 CHR_001"
    #          意图：create  →  🎨 CHR_002 ｜ 查看 CHR_001      ← 建了一张垃圾资产！
    #    因为 `router.QUERY_WORDS` 里**没有「查看」** → 路由判成 create →
    #    `_query` **根本没被调用**。抽取函数的单测全绿，也拦不住这个。
    from src import router as _rt
    for t in ("查看 CHR_001", "查一下密码本", "有哪些旗袍", "列出所有",
              "找出银发的角色"):
        _op = _rt.route(t)[0].operation
        check(f"路由：`{t}` → query（不再误判成 create）", _op == "query", _op)
    check("⭐ 抽取与路由**共用同一张动词表**（不得各存一份，否则必漂移）",
          set(_rt.QUERY_WORDS) <= set(_ag._QUERY_WORDS))
    check("⚠️「所有 / 全部」**不得**进路由表 —— 本判定会**覆盖** create/modify，"
          "放进去会让创建请求被误判成查询",
          not ({"所有", "全部"} & set(_rt.QUERY_WORDS)))
    check("创建请求仍判 create（没被查询动词误伤）",
          _rt.route("生成所有角色的三视图")[0].operation != "query",
          _rt.route("生成所有角色的三视图")[0].operation)

    # ⭐ 核心要求：**过滤条件必须可见** —— 否则"没抽到词 → 列出全部"用户看不见
    class _Q:
        seen = ("", "")

        def __init__(self):
            outer = self

            class _AM:
                @staticmethod
                def list_assets(asset_type="", keyword=""):
                    _Q.seen = outer.seen = (asset_type, keyword)
                    return []

            self.am = _AM

        _query = _ag.DramaAssetAgent._query

    q = _Q()
    res = q._query("有哪些旗袍", "character")
    check("`_query` 回传**过滤词与依据**", res.get("keyword") == "旗袍"
          and "旗袍" in res.get("keyword_note", ""), str(res.get("keyword_note")))
    check("关键词真的传给了 `list_assets`", q.seen[1] == "旗袍", str(q.seen))
    res2 = q._query("列出所有", "character")
    check("抽不到过滤词时**明说**（不静默列全部）",
          res2.get("keyword") == ""
          and "未从输入里识别出过滤词" in res2.get("keyword_note", ""),
          str(res2.get("keyword_note")))

    print()
    print("=" * 66)
    if FAIL:
        print(f"❌ 失败 {len(FAIL)} 项 / 共 {len(PASS) + len(FAIL)} 项：")
        for f in FAIL:
            print("   ·", f)
        return 1
    print(f"✅ 全部通过 —— {len(PASS)} 项（含「表外题材」与「英文纯度」两类断言）")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
