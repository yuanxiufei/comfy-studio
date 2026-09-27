# -*- coding: utf-8 -*-
"""批量生产 —— 蓝图 §十八。

蓝图原文（只给了行为，没给实现约束）：

    未来支持：一次生成 10 个废土 NPC。
    Agent 自动：CHAR-001 / CHAR-002 / … / CHAR-010
    每个角色**独立生成**：JSON · Prompt · Image · Metadata

⭐ **实现取向：不做"批量专用流水线"**，而是把「一次 10 个废土 NPC」
**展开成 10 条自然语言请求**，再各自走**正常创建流程**。

理由（这是本项目的既有纪律）：
  · 复用同一条路径 → 每项都自动获得一致的一致性 Gate / 指纹 / 版本 / 落盘，
    不会出现「批量生成的东西和单个生成的不一样」这种最难查的偏差；
  · 用户看得到每一条展开后的描述 → 不满意可直接复制去单独跑或手改；
  · 有 LLM 时由 LLM 出变体；**无 Key 时用本地池**，保证零依赖仍可跑。

⚠️ **难点是"不重复"**：`character_agent` 按世界观取预设，若照抄会生成 10 个一模一样的角色。
   故本模块的职责就是**给每一项分配不同的身份/年龄/识别点**。
"""

from __future__ import annotations

import re

# ─────────────────────────────────────────────────────────────
# NPC 池 —— 按世界观分组的「职业 / 识别点 / 年龄」
# 池子长度 ≥ 10，保证 `--count 10` 不重复（超出的按取模复用并追加序号）
# ─────────────────────────────────────────────────────────────
NPC_POOLS: dict[str, dict] = {
    "wasteland": {
        "cn": "废土",
        "jobs": ["拾荒者", "商队护卫", "水泵工", "清道夫", "佣兵",
                 "战地医生", "机械师", "哨兵", "走私贩", "流浪艺人"],
        "features": ["风沙磨花的护目镜", "缝合的皮革臂套", "背负式滤水罐",
                     "锈蚀的右侧义肢", "缠满胶带的旧步枪", "挂在颈间的辐射计",
                     "补丁摞补丁的围巾", "铁丝缠绕的护膝", "半张烧毁的面罩",
                     "一只报时的旧怀表"],
        "ages": [22, 28, 34, 41, 19, 55, 37, 26, 48, 31],
    },
    "cyberpunk": {
        "cn": "赛博朋克",
        "jobs": ["赏金猎人", "义体医生", "数据窃贼", "夜店老板", "街头黑客",
                 "快递骑手", "义体拳手", "黑市贩子", "私人侦探", "修械师"],
        "features": ["颈后数据接口", "发光瞳孔", "机械义指", "皮下植入纹路",
                     "半透明义肢外壳", "耳后散热片", "全息投影纹身",
                     "外露脊椎排线", "下颌合金补片", "手腕接线端口"],
        "ages": [25, 33, 29, 44, 21, 38, 27, 51, 35, 30],
    },
    "scifi": {
        "cn": "科幻",
        "jobs": ["舰载工程师", "导航员", "医生", "陆战队员", "通讯官",
                 "科研员", "驾驶员", "安全官", "地质勘探员", "补给官"],
        "features": ["磁力靴", "腕载终端", "背挂式生命维持包", "颈部散热环",
                     "识别胸牌", "抗荷服束带", "腰间工具挂架", "眼部光学增强器",
                     "肩部通讯天线", "便携采样箱"],
        "ages": [31, 27, 40, 24, 36, 45, 29, 34, 52, 26],
    },
    "fantasy": {
        "cn": "奇幻",
        "jobs": ["游侠", "炼金术士", "雇佣剑士", "吟游诗人", "教士",
                 "盗贼", "猎魔人", "草药师", "铁匠", "占星师"],
        "features": ["斗篷兜帽", "腰间药瓶袋", "符文护腕", "背挂长弓",
                     "悬挂的圣徽", "蒙面布巾", "银质吊坠", "皮革卷轴筒",
                     "铁匠围裙", "星盘挂饰"],
        "ages": [26, 43, 32, 24, 50, 21, 38, 47, 35, 29],
    },
    "default": {
        "cn": "通用",
        # ⚠️ 原写的是「主角 / 伙伴 / 对手 / 导师 / 路人甲」—— 那是**叙事角色位**，
        #    不是**剧中身份**。批量产出 NPC 时把它当职业用，会得到
        #    「一个24岁的民国谍战**主角**」这种把叙事标签当身份的名字（实测踩到）。
        #    现改为**与题材无关的社会身份位**（任何作品里都成立）。
        "jobs": ["主事者", "副手", "学徒", "手艺人", "行商",
                 "医者", "护卫", "信使", "邻里", "外来者"],
        "features": ["标志性围巾", "随身旧物", "磨损的随身包", "一枚戒指",
                     "肩上的伤疤", "别在衣襟的徽章", "老旧的怀表", "手写的信笺",
                     "木柄工具", "磨破的袖口"],
        "ages": [24, 32, 29, 41, 19, 55, 36, 27, 46, 33],
    },
}

# ─────────────────────────────────────────────────────────────
# 场景 / 道具池 —— 同样按世界观分组，`default` 是**题材无关的功能类目**
# ─────────────────────────────────────────────────────────────
# ⚠️ 原实现把这两张表**写死在 `plan()` 里且只有一份废土清单**，于是
#    「10个民国谍战道具」会产出「能源步枪 / 信号发生器 / 便携净水器」（实测踩到）；
#    场景同理。与 `NPC_POOLS` 是同一类问题：**把某个题材的具体值当成通用值**。
SCENE_POOLS: dict[str, list[str]] = {
    "wasteland": ["地下指挥中心", "废弃街区", "城郊公路", "临时营地", "水泵站",
                  "医疗帐篷", "修理厂", "哨塔", "集市", "地下通道"],
    # 题材无关的**功能空间**（任何作品里都存在这些"位"）
    "default": ["主厅堂", "出入口", "连接通道", "私密房间", "工作间",
                "储物处", "集会处", "高处瞭望点", "边缘地带", "后勤区"],
}

PROP_POOLS: dict[str, list[str]] = {
    "wasteland": ["能源步枪", "多功能工具刀", "便携净水器", "信号发生器", "护目镜",
                  "战术背包", "医疗箱", "燃料罐", "对讲机", "工具箱"],
    # 题材无关的**通用器物类目**
    "default": ["随身携带物", "记录工具", "照明工具", "容器", "成套工具",
                "通讯物", "防护物", "计时物", "凭证文书", "纪念物"],
}

# 输入里的数量：「10个」「十个人」…
_CN_DIGIT = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
             "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def pool_for(world: str) -> tuple[dict, bool]:
    """取世界观对应的 NPC 池 → `(池, 是否命中题材池)`。

    ⚠️ 必须**返回是否命中**：原实现未命中时静默回落到通用池，
    于是「10个民国谍战NPC」用得是通用身份而**全程不说** ——
    用户看到「主事者/行商/医者」不会知道那是兜底，也就无从修正
    （本项目反复强调：**静默的机制比报错更难查**）。
    """
    w = (world or "").lower()
    for k, v in NPC_POOLS.items():
        if k != "default" and k in w:
            return v, True
    return NPC_POOLS["default"], False


def _typed_pool(pools: dict, world: str) -> tuple[list[str], bool]:
    """从 `SCENE_POOLS` / `PROP_POOLS` 取题材清单 → `(清单, 是否命中)`。"""
    w = (world or "").lower()
    for k, v in pools.items():
        if k != "default" and k in w:
            return v, True
    return pools["default"], False


def user_items(text: str) -> list[str]:
    """抽**用户自己给的**名称清单：「10个民国特工：报务员、线人、舞女」→ 那 3 个词。

    ⭐ 这是「任何一部小说都行」最直接的入口 —— **用户比任何池子都清楚
    他的作品里有哪些身份 / 场所 / 器物**。故 `plan()` 里它**优先于题材池**。
    走的是**标点结构**（`：` 之后的 `、`/`，` 分隔项），不依赖任何题材词表。
    """
    m = re.search(r"[：:]\s*(.+)$", text or "")
    if not m:
        return []
    out: list[str] = []
    for w in re.split(r"[、,，/|]+", m.group(1)):
        w = w.strip(" 。．.的")
        if 2 <= len(w) <= 10 and w not in out:
            out.append(w)
    return out


def parse_count(text: str, default: int = 10) -> int:
    """从输入里取数量（「一次生成10个」→ 10）。取不到用 default。"""
    m = re.search(r"(\d{1,2})\s*个", text or "")
    if m:
        return max(1, min(60, int(m.group(1))))
    m = re.search(r"([一二两三四五六七八九十])个", text or "")
    if m:
        return _CN_DIGIT.get(m.group(1), default)
    return default


# 这批词是"容器"不是"内容" —— 留着会让生成文本变成
# 「一个28岁的**废土NPC**商队护卫」（粘成一团），也让职业抽取取错
_NOISE = ("NPC", "npc", "Npc", "角色", "人物", "群像", "们")


def _strip_count(text: str) -> str:
    """去掉数量词与容器词，只留「世界观 + 题材」这类真正的内容。

    ⚠️ 必须去掉 `NPC` —— 否则生成的是「一个28岁的废土NPC商队护卫」，
    职业抽取（`_find_occupation`）的兜底正则会取到句尾修饰词而非职业（实测踩到）。
    """
    t = re.sub(r"(\d{1,2}|[一二两三四五六七八九十])\s*个", "", text or "")
    t = re.sub(r"一次(生成|做|建|批量)?", "", t)
    for w in _NOISE:
        t = t.replace(w, "")
    # ⚠️ 必须**丢掉「：」之后的部分** —— 那是**规格清单**（身份/场所/器物名），
    #    不是"世界观+题材"这类内容。不去掉会把它整串拼进生成文本，产出
    #    「一个24岁的民国谍战：报务员、线人、舞女、巡捕**报务员**，标志性围巾」
    #    这种把清单和身份粘成一团的东西（实测踩到，是我引入的）。
    t = re.split(r"[：:]", t, maxsplit=1)[0]
    return t.strip(" ，,。的")


def plan(text: str, count: int = 0, asset_type: str = "character",
         world: str = "") -> tuple[list[dict], list[str]]:
    """把一次批量请求**展开**成 N 条独立请求 → `(items, notes)`。

    ⭐ **优先级（与 `src/generic.py` 同一套原则）**：
      ① **用户自己给的名字**（`：` 后面的清单）—— 「用户比任何池子都清楚他的作品」；
      ② **命中题材池** → 用该题材的具体值（最贴）；
      ③ **未命中** → 用**题材无关的通用骨架**，并**明说**（不假装具体）。

    ⚠️ 第 ③ 条此前是**静默**的：未命中就悄悄套用废土清单，于是
    「10个民国谍战道具」产出了「能源步枪 / 信号发生器 / 便携净水器」，
    而报告里一个字都没提。这是本项目最忌讳的失败形态。

    展开规则（按资产类型不同）：
      · 角色 / NPC → 分配不同**身份 + 识别点 + 年龄**
      · 场景      → 分配不同**空间**
      · 道具      → 分配不同**品类**
      · 服装 / 表情 / 动作 → 批量意义不大，仍按序号区分（提示用户）
    """
    n = count or parse_count(text)
    base = _strip_count(text)
    given = user_items(text)
    items: list[dict] = []
    notes: list[str] = []

    if asset_type == "character":
        pool, matched = pool_for(world or base)
        jobs = given or pool["jobs"]
        if given:
            notes.append(f"✅ 身份取**你给的清单**（{len(given)} 项）："
                         + "、".join(given))
        elif not matched:
            notes.append(
                f"ℹ️ **未命中题材池**（现有的池：{'、'.join(k for k in NPC_POOLS if k != 'default')}；"
                f"本次 world={world or base or '（空）'}）→ 用**与题材无关的通用身份**"
                f"（{'、'.join(pool['jobs'][:4])}…）。想让身份贴合你的作品，"
                f"直接在描述里列出来即可，如「10个<你的题材>人物：身份1、身份2、…」")
        for i in range(n):
            job = jobs[i % len(jobs)]
            feat = pool["features"][i % len(pool["features"])]
            age = pool["ages"][i % len(pool["ages"])]
            # 超出清单长度时补序号，保证不重名
            suffix = f"（第{i // len(jobs) + 1}批）" if i >= len(jobs) else ""
            items.append({
                "index": i + 1,
                "label": f"{age}岁 · {job}{suffix}",
                "text": f"一个{age}岁的{base or pool['cn']}{job}{suffix}，{feat}",
            })
    elif asset_type == "environment":
        pool, matched = _typed_pool(SCENE_POOLS, world or base)
        spaces = given or pool
        if given:
            notes.append(f"✅ 空间取**你给的清单**：{'、'.join(given)}")
        elif not matched:
            notes.append("ℹ️ **未命中题材池** → 用**题材无关的功能空间**"
                         "（主厅堂/出入口/工作间…）；给出具体场所可直接照用，"
                         "如「10个<题材>场景：场所1、场所2、…」")
        for i in range(n):
            space = spaces[i % len(spaces)]
            items.append({
                "index": i + 1,
                "label": space,
                "text": f"{base or ''}的{space}".lstrip("的"),
            })
    elif asset_type == "prop":
        pool, matched = _typed_pool(PROP_POOLS, world or base)
        names = given or pool
        if given:
            notes.append(f"✅ 品类取**你给的清单**：{'、'.join(given)}")
        elif not matched:
            notes.append("ℹ️ **未命中题材池** → 用**题材无关的通用类目**"
                         "（随身携带物/记录工具/照明工具…）；给出具体物件可直接照用，"
                         "如「10个<题材>道具：物件1、物件2、…」")
        for i in range(n):
            p = names[i % len(names)]
            items.append({"index": i + 1, "label": p, "text": f"设计一个{p}"})
    else:
        # 服装 / 表情 / 动作：批量意义有限，仍按序号区分并在 CLI 里提示
        notes.append(f"ℹ️ `{asset_type}` 批量意义有限（同质化高）—— "
                     f"建议逐个给具体描述；本次仍按序号展开 {n} 条")
        for i in range(n):
            items.append({
                "index": i + 1,
                "label": f"{base or asset_type} #{i + 1}",
                "text": f"{base}（第 {i + 1} 件）",
            })
    return items, notes


def roster(results: list[dict]) -> str:
    """产出「花名册」—— 蓝图 §十八 要求列出自动分配的 ID。"""
    rows = ["| # | ID | 名称 | 版本 | 状态 |", "|---|---|---|---|---|"]
    ok = 0
    for r in results:
        if r.get("ok") is False or "asset_id" not in r:
            rows.append(f"| {r.get('index', '?')} | ❌ | "
                        f"{r.get('error', '失败')[:40]} | — | — |")
            continue
        ok += 1
        rows.append(f"| {r.get('index', '?')} | `{r['asset_id']}` | "
                    f"{r.get('name', '')[:20]} | {r.get('version', '')} | "
                    f"{r.get('status', '')} |")
    head = (f"共 {len(results)} 项，成功 **{ok}** 项"
            + (f"，失败 {len(results) - ok} 项" if ok < len(results) else ""))
    return head + "\n\n" + "\n".join(rows)
