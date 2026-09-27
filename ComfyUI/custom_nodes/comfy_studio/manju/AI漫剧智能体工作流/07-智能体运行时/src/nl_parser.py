# -*- coding: utf-8 -*-
"""自然语言 → 结构化字段（**规则版，无需任何 API Key**）。

`llm_client.py` 用大模型解析更准，但**没 Key 就跑不起来**。
本模块是兜底：有 Key 用 LLM，没 Key 用规则，**两条路径输出同一个 `ParsedInput`**，
下游完全无感 —— 这是「复制到另一台电脑即可运行」的前提。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ⚠️ 场所后缀表**只有一份**（在 `generic`）—— 类型判定与场所抽取必须用**同一张表**，
#    否则两处判据会分叉（`generic` 里对 `nl_parser` 是**函数内惰性导入**，故无循环）
from .generic import PLACE_SUFFIX

# ── 词表（来源：用户素材 SYSTEM_PROMPT.md §5 风格 / §7 材质 / §8 配色）──

WORLD_STYLES: dict[str, list[str]] = {
    "wasteland": ["废土", "末日", "末世", "核战", "wasteland"],
    "cyberpunk": ["赛博朋克", "赛博", "义体", "机械义", "cyberpunk", "霓虹"],
    "scifi": ["科幻", "未来", "太空", "火星", "星际", "机甲", "飞船", "scifi"],
    "fantasy": ["奇幻", "魔法", "精灵", "龙", "幻想", "fantasy"],
    "dark_fantasy": ["黑暗奇幻", "暗黑", "血族", "吸血鬼", "哥特"],
    "ancient": ["古代", "古装", "古风", "武侠", "江湖", "仙侠", "东方幻想"],
    "western_fantasy": ["西方幻想", "骑士", "中世纪", "城堡", "王国"],
    "steampunk": ["蒸汽朋克", "蒸汽", "齿轮", "steampunk"],
    "modern": ["现代", "都市", "当代"],
    "military": ["军事", "军人", "佣兵", "雇佣兵", "特种", "战场", "军用"],
    "mecha": ["机甲", "机器人", "机战", "mecha"],
}

# ⚠️ 材质是**有限集合**，故扩充是正当的（不像"形制/器物"是无限词，只能靠**语法**抽）。
#    2026-09-24 补：此前缺「丝/丝绸/缎/纱/呢/绒」等 —— 而它们在民国/仙侠/古代题材里
#    极常见（旗袍、道袍、古代服饰）。缺了它们的后果不只是"抽不到"：
#    `material_en = tr('丝')` 会**原样返回中文**，把中文送进英文 prompt
#    （本项目第 7 次同款问题的变体）→ 现已同时补 `ZH2EN` 与 `MATERIALS`。
MATERIALS = ["丝绸", "丝", "缎", "绢", "纱", "绡", "呢", "绒", "锦", "麻", "棉麻",
             "帆布", "棉", "亚麻", "牛仔", "皮革", "人造皮革", "防水织物", "战术尼龙",
             "凯夫拉纤维", "碳纤维", "钛合金", "铝合金", "磨砂钢", "镀铬金属",
             "黄铜", "铜", "铁", "钢", "陶瓷", "玻璃", "亚克力", "橡胶", "硅胶",
             "毛皮", "羽毛", "木材", "石材", "纸质", "魔法晶体", "生物组织"]

COLORS = ["黑", "白", "灰", "银", "金", "红", "暗红", "酒红", "橙", "黄",
          "绿", "青", "蓝", "紫", "粉", "棕", "米", "藏青"]

GENDER_WORDS = {"女": "female", "男": "male", "女性": "female", "男性": "male",
                "少女": "female", "女孩": "female", "少年": "male", "男孩": "male",
                "女人": "female", "男人": "male", "女士": "female", "先生": "male"}

PROP_WORDS = ["枪", "步枪", "狙击枪", "手枪", "刀", "剑", "匕首", "斧", "弓",
              "道具", "装置", "机械臂", "义肢", "头盔", "护甲", "盾", "药",
              "注射器", "终端", "面板", "钥匙", "戒指", "项链"]
COSTUME_WORDS = ["服装", "衣服", "套装", "制服", "战衣", "盔甲", "长袍",
                 "风衣", "外套", "衬衫", "皮夹克", "夹克", "裤子", "长裤",
                 "裙", "斗篷", "披风", "护甲", "背心", "工装"]
NO_COMPLETE_WORDS = ["不要自动补全", "别自动补全", "严格按我的设定", "不要补全"]

HAIR_WORDS = ["长发", "短发", "中长发", "及腰", "马尾", "双马尾", "编发", "大背头",
              "寸头", "卷发", "直发", "刘海", "狼尾", "蘑菇头", "波波头", "背头",
              "油头", "碎发", "乱发", "束发", "丸子头"]

EQUIP_WORDS = ["机械左臂", "机械右臂", "机械手臂", "机械腿", "机械右腿", "机械左腿",
               "义眼", "机械义眼", "义肢", "军靴", "护目镜", "面具", "头盔",
               "背包", "枪套", "匕首", "佩剑", "手杖", "护甲", "肩甲", "披风",
               "项链", "戒指", "腰带", "手套", "斗篷"]

JOBS = ["佣兵", "雇佣兵", "杀手", "刺客", "医生", "护士", "侦探", "警探", "警察",
        "工程师", "科学家", "教授", "博士", "士兵", "军人", "将军", "元帅",
        "黑客", "机修师", "拾荒者", "猎人", "商人", "老板娘", "船长", "飞行员",
        "骑士", "法师", "剑客", "武僧", "皇帝", "公爵", "公主", "王子", "教主",
        "记者", "教师", "学生", "程序员", "设计师", "司机", "厨师", "农民",
        # 批量 NPC 池用到的职业（蓝图 §十八「一次生成 10 个废土 NPC」）——
        # 池子里的词必须在这里，否则职业抽不出来、资产名会取到修饰词
        "机械师", "街头黑客", "主角", "路人甲",
        "商队护卫", "水泵工", "清道夫", "战地医生", "哨兵", "走私贩", "流浪艺人",
        "赏金猎人", "义体医生", "数据窃贼", "夜店老板", "快递骑手", "义体拳手",
        "黑市贩子", "私人侦探", "修械师", "舰载工程师", "导航员", "陆战队员",
        "通讯官", "科研员", "驾驶员", "安全官", "地质勘探员", "补给官",
        "游侠", "炼金术士", "雇佣剑士", "吟游诗人", "教士", "盗贼", "猎魔人",
        "草药师", "铁匠", "占星师", "伙伴", "对手", "导师", "店主", "守卫",
        "信使", "工匠", "旅人"]

MODIFY_VERBS = ["改成", "换成", "改为", "变成", "增加", "加上", "去掉", "删除", "减掉"]

FIELD_MAP = {
    "头发": "hair", "发色": "hair_color", "发型": "hair_style",
    # ⚠️ 「眼睛 / 眼瞳 / 瞳孔 / 瞳色」**全部**要映到 `eye_color`：
    #    ① 原表把「眼睛」映到 `eyes`，而 `_apply_changes` 只处理 `eye_color`
    #       → 「把她的眼睛换成蓝色」是**静默无效**（报了"未识别出可改字段"但不改）；
    #    ② 「瞳孔」压根不在表里 → 「把她的**瞳孔**换成蓝色」连字段都解析不出，
    #       于是 §四·补 A「瞳色 100% 不可改动」这条**最该报的约束反而沉默**（实测踩到）。
    "眼睛": "eye_color", "眼瞳": "eye_color",
    "瞳孔": "eye_color", "瞳色": "eye_color",
    "眼型": "eye_shape", "服装": "clothing", "衣服": "clothing",
    "装备": "equipment", "武器": "equipment", "颜色": "color",
    "机械臂": "cybernetic_arm", "机械腿": "cybernetic_leg", "义眼": "cybernetic_eye",
    "年龄": "age", "体型": "body", "身材": "body",
}


@dataclass
class ParsedInput:
    raw: str = ""
    asset_type: str = "character"
    operation: str = "create"
    name: str = ""
    age: int | None = None
    gender: str = ""
    occupation: str = ""
    role: str = ""
    world: str = ""
    camp: str = ""
    appearance_hints: list[str] = field(default_factory=list)
    hair_hints: list[str] = field(default_factory=list)
    clothing_hints: list[str] = field(default_factory=list)
    equipment_hints: list[str] = field(default_factory=list)
    color_hints: list[str] = field(default_factory=list)
    material_hints: list[str] = field(default_factory=list)
    target_asset: str = ""
    # 输入里**提到的资产 ID**（如「给 CHR_001 建表情集」）——
    # 表情/动作资产必须挂在角色上（`EXP_<角色>_<表情名>`），故需要它。
    related_ids: list[str] = field(default_factory=list)
    change_fields: list[str] = field(default_factory=list)
    no_auto_complete: bool = False
    parser: str = "rule"
    confidence: float = 0.5


def _find_age(text: str) -> int | None:
    m = re.search(r"(\d{1,3})\s*(?:岁|years?\s*old)", text)
    if m and 1 <= int(m.group(1)) <= 200:
        return int(m.group(1))
    for k, v in {"十": 10, "二十": 20, "三十": 30, "四十": 40, "五十": 50,
                 "六十": 60, "七十": 70, "八十": 80, "九十": 90, "一百": 100}.items():
        if f"{k}岁" in text:
            return v
    return None


def _find_gender(text: str) -> str:
    for k, v in GENDER_WORDS.items():
        if k in text:
            return v
    return ""


def _find_world(text: str) -> str:
    """题材 / 世界观 —— **自由文本，不是 11 个枚举值之一**。

    ⚠️ 原实现只返回 `WORLD_STYLES` 的 11 个键之一，**未命中即空串**。
    实测后果（「任何一部小说都行」这条要求下的硬伤）：
      · 「民国谍战剧」→ `world=""` → 资产名被拼成「主角-**未定**」
        （批量产出 10 个「×-未定」）；
      · `WORLD_RENDER` 落默认值，题材渲染段丢失。

    ⭐ 现改为两级：
      ① **命中 11 个题材键** → 返回键（它们有专门的预设与渲染，最具体）；
      ② **未命中** → 回退到**时代词**（如「民国」「清朝」「未来」）作为自由文本
         —— 于是 world 能表达**任意**作品的年代/题材，不再只有 11 种说法。
    """
    best, blen = "", 0
    for style, kws in WORLD_STYLES.items():
        for kw in kws:
            if kw in text and len(kw) > blen:
                best, blen = style, len(kw)
    if best:
        return best
    from .generic import era_from_text
    return era_from_text(text)[0]


def _find_occupation(text: str) -> str:
    # ① 精确词表（**取最长命中** —— 「战地医生」比「医生」更具体）
    hits = [j for j in JOBS if j in text]
    if hits:
        return max(hits, key=len)

    # ② 「N岁的X」—— 最强信号，优先于「的」兜底。
    #    否则「一个28岁的废土商队护卫，缝合的皮革臂套」会被下面那条
    #    兜底正则取到**句尾的修饰词**「皮革臂套」（实测踩到）。
    m = re.search(r"\d{1,3}\s*岁(?:的)?([\u4e00-\u9fa5]{2,6}?)(?:，|,|。|$)", text)
    if m:
        return m.group(1)

    # ③ 兜底：「的X」但**排除句尾修饰词**（前面常是「缝合的/磨损的/旧的」这类动宾）
    m = re.search(r"的([\u4e00-\u9fa5]{2,4})(?:，|,|。|$)", text)
    if m and not any(w in text for w in ("缝合的", "磨损的", "旧的", "破的")):
        return m.group(1)
    return ""


def _detect_modify(text: str) -> tuple[bool, list[str], str]:
    is_mod = any(v in text for v in MODIFY_VERBS) or bool(
        re.search(r"把(她|他|它|这个|那个)", text))
    fields: list[str] = []
    for k, v in FIELD_MAP.items():
        if k in text and v not in fields:
            fields.append(v)
    from .schema import parse_id
    target = ""
    m = re.search(r"((?:CHR|CST|PRP|ENV)_\d{1,3}|(?:CHAR|COSTUME|PROP|SCENE)-\d{1,3})",
                  text, re.IGNORECASE)
    if m:
        target = m.group(1)
    elif "她" in text or "他" in text:
        target = "previous"
    return is_mod, fields, target


def _collect_color_hints(text: str) -> list[str]:
    """按**在原文中出现的先后**排序取色词。

    ⚠️ 不能按词表顺序取（`COLORS` 里「白」在「银」之前）——「银白色」会解析成「白」。
    按出现位置排序后，「银白色」的首个命中是「银」✓。
    """
    hits = [(text.find(c), c) for c in COLORS if c in text]
    return [c for _, c in sorted(hits)]


def _object_after_measure(text: str, words: list[str], span: int = 12) -> str:
    """找「**量词 + 宾语**」里的宾语属于哪一类。

    必要性（实测踩到）：「给**女佣兵**设计一套**风衣**」——
    句中出现「女」（性别词），按"有人物词就是角色"的规则会被误判成角色，
    但用户要的明明是**服装资产**。

    「量词 + 宾语」是更可靠的信号：`设计一套风衣` / `设计一把步枪`。
    """
    # ⚠️ 必须是 `{1,N}`（1 到 N 个字），不是 `{N}`（恰好 N 个字）——
    # 写 `{12}` 会要求宾语恰好 12 字，「破损军用风衣」（6 字）就永远匹配不上。
    for m in re.finditer(r"(?:套|件|条|把|支|柄|台|个)([\u4e00-\u9fa5A-Za-z]{1,%d})"
                         % span, text):
        frag = m.group(1)
        # ⚠️ **把字句**：`把他的义肢换成机械臂` 里的「把」是**介词**。
        #    不加这条护栏会把"改角色"判成**道具**（实测：指代解析随之改错对象）。
        #    与 `_measure_object` 同一护栏 —— 两处都出现「量词」形态，必须一致。
        if frag[:1] in "她他它我你您咱这那其":
            continue
        for w in words:
            if w in frag:
                return w
    return ""


# ⭐ 量词按"通常计量什么"分组 —— **语法信号**，与题材无关、不随题材失效
#   （「设计一柄油纸伞」的「柄」是汉语事实，不需要知道"伞"是什么）
COSTUME_MEASURES = "套件身袭"
PROP_MEASURES = "把支柄台只副盏枚根杆架罐箱盒部本挺管盏座"
NEUTRAL_MEASURES = "个张块面"
_MEASURE_RE = re.compile(
    r"([%s%s%s])([\u4e00-\u9fa5A-Za-z]{1,12})"
    % (COSTUME_MEASURES, PROP_MEASURES, NEUTRAL_MEASURES))


# 表情 / 动作（EXP_ / POS_）—— 必须挂在角色上，故识别优先于「有人物词就是角色」
EXPRESSION_WORDS = ("表情集", "表情图", "表情表", "表情库", "神态集", "表情")
POSE_WORDS = ("动作集", "动作图", "动作表", "姿势集", "姿态集", "动作库", "姿势", "姿态")

# 场景**名词**（ENV_）—— ⚠️ 这里**只放"空间/建筑"本身的名词**，
# **绝不能放世界观形容词**（废土 / 赛博 / 末日 / 霓虹 …）。
# 因为「一个30岁的**废土**女佣兵」含"废土"，若把它当场景词 → 角色被误判成场景。
# 世界观与题材由 `scene_agent.SCENE_PRESETS` 的 keys 单独匹配（那是**选定预设**用的，
# 只在类型已判定为 environment 之后才走）。
SCENE_WORDS = (
    # 军事/科技
    "指挥中心", "控制室", "指挥部", "舰桥", "实验室", "基地", "舱内", "舱",
    "军营", "工厂", "仓库", "机库",
    # 废墟/城市
    "废墟", "遗迹", "残垣", "街道", "市区", "都市", "巷", "天台", "屋顶",
    "广场", "港口", "码头", "车站", "桥",
    # 自然
    "荒野", "沙漠", "雪原", "冰川", "荒原", "森林", "山林", "峡谷", "海岸", "洞穴",
    # 古风
    "宫殿", "大殿", "厅堂", "庭院", "府邸", "神殿", "祭坛", "客栈", "酒馆",
    # 战场
    "战场", "战壕", "战地",
    # 地下/室内
    "地下", "地窟", "隧道", "房间", "卧室", "客厅", "公寓", "居所", "室内",
    # 其他常见
    "教堂", "墓地", "医院", "学校", "图书馆",
)


_LEAD_VERBS = ("帮我设计", "帮我做", "帮我画", "帮我生成", "设计", "做一个", "做", "画一个", "画", "生成")
_MEASURE_FILLERS = "一个一把一件一套一条一只台的，,。 "


def short_name(raw: str) -> str:
    """从整句输入里裁出可读的资产名（供道具/服装/场景共用）。

    例：「给女佣兵设计一套破损军用风衣」→「破损军用风衣」
    ⚠️ 不裁的话，资产名会是**整句用户输入**（实测：`CST_001` 的名字是
    「给女佣兵设计一套破损军用风衣」），它还会整串进英文 prompt。
    """
    s = (raw or "").strip()
    # 优先取「量词 + 宾语」那一节
    m = re.search(r"(?:套|件|条|把|支|柄|台|个)([\u4e00-\u9fa5A-Za-z]{2,12})", s)
    if m:
        s = m.group(1)
    else:
        for v in _LEAD_VERBS:
            if s.startswith(v):
                s = s[len(v):]
                break
        s = s.lstrip(_MEASURE_FILLERS)
    return (s[:20] or "").strip()


def _measure_object(text: str, span: int = 12) -> tuple[str, str]:
    """找「量词 + 宾语」→ `(量词定型, 宾语片段)`。

    ⭐ **量词是"语法信号"**：哪些量词计量衣物、哪些计量器物，是**汉语的语法事实**，
    有限且**与题材无关** —— 不会像名词表那样"用户换个题材就失效"。
    这正是本项目通用性的支点：**能靠语法判的，绝不靠词表**。

    实测踩到（加这个的原因）：
      · 「设计一柄**油纸伞**」→ 伞不在 `PROP_WORDS` → 被当成**角色**，
        连资产名都变成整句话；
      · 「设计一个民国**密码本**」「设计一台老式**留声机**」同理。

    返回的定型 ∈ `costume` / `prop` / `""`（中性量词，需再看人物信号）。

    ⚠️ **必须排除"把字句"** —— 实测踩到（冒烟测试抓出来的）：
    `把她的头发换成银白色` 里的「**把**」是**介词**（把字句），不是量词；
    不加护栏会把"改发色"判成**道具**，于是指代「她」被解析到 `PRP_001` 上。
    判据：量词后面紧跟**代词/指代词**（她他它我你您咱这那其）→ 跳过，继续往后找。
    """
    for m in _MEASURE_RE.finditer(text or ""):
        q, frag = m.group(1), m.group(2)
        if frag[:1] in "她他它我你您咱这那其":
            continue                                   # 把字句/介词结构，不是量词
        if q in COSTUME_MEASURES:
            return "costume", frag
        if q in PROP_MEASURES:
            return "prop", frag
        return "", frag                                # 中性量词（个/张/块…）
    return "", ""


def _has_place_word(text: str) -> bool:
    """某个小句**以场所字结尾** → 视为场景。

    ⭐ 同样是**结构信号**（`PLACE_SUFFIX` 是**字**表，不是词表）：
    「民国上海洋行的大**厅**」→「厅」结尾 → 场景 ✓。

    ⚠️ 判据是"**以**场所字结尾"，**不是**"**含**场所字" —— 实测踩到两次：
      · 「一位药铺**的**掌柜」：中间有「铺」→ 含判据会判成场景，但中心语是「掌柜」；
      · 「一个老练**的**船工」：同理，「船」不是中心语。
    **汉语名词短语的中心语在最后**，故只看每个小句的**结尾字**。
    （同一坑在 `generic.prep_place` 也踩过 —— 那里已注明"含判据会把『在**进行**改革』
    抽成场所"，两处现已统一为"以结尾判"。）

    ⚠️ 调用方**必须先确认没有人物信号** —— 否则「一个在**街**上的女佣兵」会被判成场景。
    """
    for seg in re.split(r"[，,。；;！!？?、\s]", text or ""):
        seg = (seg or "").rstrip("上里中内外的")
        if len(seg) >= 2 and seg[-1] in PLACE_SUFFIX:
            return True
    return False


def _tail_has(text: str, words) -> str:
    """词表命中要求落在**小句结尾** → 返回命中的词（没有则空串）。

    ⚠️ 不能用「含」—— 实测：「一位**药铺**的掌柜」因 `PROP_WORDS` 里有**单字「药」**
    被判成道具；「民国上海洋**行**」也会因「行」这类字命中别的表。
    这与 `_has_place_word` 是**同一条语法事实**：**汉语名词短语的中心语在最后**，
    故"资产是什么"应由**结尾**决定，不是"句中出现过什么字"。
    """
    for seg in re.split(r"[，,。；;！!？?、\s]", text or ""):
        for w in words:
            if w and seg.endswith(w):
                return w
    return ""


def _detect_asset_type(text: str) -> str:
    """判定资产类型。**顺序即优先级**，每一步的理由见行内注释。

    ⭐ 通用性原则（2026-09-24）：**能靠语法/结构判的，绝不靠名词表**。
    凡是"因为某个名词不在我们的表里就判错"的地方，都是「任何一部小说都行」
    的漏洞。故本函数里有三道**结构信号**（量词 / 场所字 / 人物信号），
    它们不随题材失效。
    """
    # ① 表情 / 动作：带「集 / 图 / 表」标记，**无歧义**，且优先于角色 ——
    #    「给女佣兵建表情集」含「女」，若先判人物词会被误判成角色。
    if any(k in text for k in EXPRESSION_WORDS):
        return "expression"
    if any(k in text for k in POSE_WORDS):
        return "pose"

    # ② 「量词 + 宾语」—— 用户要做的"那个东西"是什么，比句中提到谁更重要
    if _object_after_measure(text, COSTUME_WORDS):
        return "costume"
    if _object_after_measure(text, PROP_WORDS):
        return "prop"

    # ③ 人物信号（性别 / 年龄）—— 只有**中性量词**与场景判定要它做护栏。
    has_person = bool(_find_gender(text)) or bool(re.search(r"\d{1,3}\s*岁", text))

    # ④ ⭐ **量词定型**（结构信号，**不受人物信号影响** —— 这是②的设计初衷：
    #    「给女佣兵设计一件风衣」里有「女」，但它要的是服装资产）
    kind, frag = _measure_object(text)
    # ⚠️ 但**宾语本身以场所字结尾时要让位**：量词是"主要计量什么"，不是排他的 ——
    #    「一**座**香火冷清的城隍**庙**」的「座」也计量建筑。实测踩到：不让位的话
    #    它会被判成道具。（「座」既是器物量词也是建筑量词，靠宾语结尾字消歧。）
    if kind and not (frag and frag[-1] in PLACE_SUFFIX):
        return kind

    # ⑤ ⭐ 句中点了**职业词** → 角色（「一位药铺的掌柜」「在码头当搬运工的商人」）
    #    ⚠️ 必须在场景判定**之前**：否则「药**铺**的掌柜」会因「铺」是场所字被判成场景。
    #    用 `JOBS` 词表而不是 `_find_occupation()` —— 后者的「的」兜底会把
    #    「洋行的大厅」也抽成"职业"，反而把场景判错。
    if any(j in text for j in JOBS):
        return "character"

    # ⑥ 场景**名词**（不含世界观形容词）—— 有明确空间名词、且句中不是在描述某个人
    if not has_person and any(k in text for k in SCENE_WORDS):
        return "environment"

    # ⑦ ⭐ **场所字结尾** → 场景（结构信号；⑧ 之前必须先过这一关，
    #    否则「民国上海洋行的大厅」会掉进 ⑧ 被当成道具）
    if not has_person and _has_place_word(text):
        return "environment"

    if not has_person and any(k in text for k in ("场景", "环境")):
        return "environment"

    # ⑧ 兜底：道具 / 服装关键词（⚠️ 用 `_tail_has` 按**结尾**命中，不用「含」）
    if not has_person and _tail_has(text, PROP_WORDS):
        return "prop"
    if not has_person and _tail_has(text, COSTUME_WORDS):
        return "costume"

    # ⑨ ⭐ **中性量词**（个/张/块…）—— 可人可物，故要两道护栏：
    #    · `has_person`：句中在描述人 → 是角色（「一个30岁的女佣兵」）
    #    · **宾语抽得出职业** → 是角色（「设计一个主角」不该变成道具）
    #    两道都过才按"器物"处理（「设计一个民国密码本」→ 道具）。
    if not has_person and frag and not _find_occupation(frag):
        return "prop"

    return "character"


# 输入里出现的**资产 ID**（项目规范前缀 + 蓝图前缀两种写法都认）
_ID_IN_TEXT = re.compile(
    r"(?:^|[^A-Za-z0-9_])((?:CHR|CST|PRP|ENV|EXP|POS|SHT|VID|AUD)_[A-Za-z0-9_]+"
    r"|(?:CHAR|COSTUME|PROP|SCENE|POSE)-\d{1,3}[A-Za-z0-9_\-]*)")


def _collect_ids(text: str) -> list[str]:
    out: list[str] = []
    for m in _ID_IN_TEXT.finditer(text):
        v = m.group(1).rstrip("_")
        if v not in out:
            out.append(v)
    return out


def parse(text: str, default_type: str = "") -> ParsedInput:
    """规则解析入口。`default_type` 非空时强制该类型（供 CLI --type 覆盖）。"""
    text = (text or "").strip()
    p = ParsedInput(raw=text)
    p.related_ids = _collect_ids(text)
    p.no_auto_complete = any(w in text for w in NO_COMPLETE_WORDS)

    is_mod, fields, target = _detect_modify(text)
    if is_mod:
        p.operation, p.change_fields, p.target_asset = "modify", fields, target

    p.asset_type = default_type or _detect_asset_type(text)
    p.age = _find_age(text)
    p.gender = _find_gender(text)
    p.occupation = _find_occupation(text)
    p.world = _find_world(text)
    if p.asset_type == "character":
        # ⚠️ `world` 为空时**不要拼「-未定」**：那串本意是"让人看见没识别出题材"，
        #    代价却是**污染资产名**（实测批量产出 10 个「主角-未定」「店主-未定」）。
        #    "没识别出题材"这个事实由 `world=""` 本身 + 报告承担，不必写进名字。
        # ⚠️ 但「角色」这个**身份兜底不能一起去掉** —— 第一版写成
        #    `f"{p.occupation}-{p.world}"`，于是职业抽不到时名字变成「**-民国**」
        #    （前导连字符，实测端到端跑出来）。故 occupation 空时仍用「角色」。
        p.name = (f"{p.occupation or '角色'}-{p.world}" if p.world
                  else (p.occupation or ""))

    p.hair_hints = [h for h in HAIR_WORDS if h in text] + \
        [f"{c}发" for c in COLORS if f"{c}发" in text]
    p.equipment_hints = [e for e in EQUIP_WORDS if e in text]
    p.color_hints = _collect_color_hints(text)
    p.material_hints = [m for m in MATERIALS if m in text]
    p.clothing_hints = [w for w in ("风衣", "外套", "制服", "战衣", "盔甲", "斗篷",
                                    "军装", "长袍", "衬衫", "皮夹克") if w in text]
    p.appearance_hints = p.hair_hints + p.color_hints

    signals = sum(bool(x) for x in (p.age, p.gender, p.occupation, p.world,
                                    p.hair_hints, p.equipment_hints))
    p.confidence = min(0.9, 0.3 + 0.1 * signals)
    return p
