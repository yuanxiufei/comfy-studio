# -*- coding: utf-8 -*-
"""Character Agent —— 把「一句话」补全成完整角色设定（蓝图 §三）。

═══════════════════════════════════════════════════════════════════
铁则（用户素材 SYSTEM_PROMPT.md §21「优先级」）
═══════════════════════════════════════════════════════════════════
    1. 用户明确要求   2. 当前项目设定   3. Agent 标准规范   4. 自动补全内容

故本模块**只填空字段，绝不覆盖用户已给的**（`_set_if_empty`）。

⚠️ 预设表是**中英双语**的（`*_cn` / `*_en` 成对）：
   中文进 `prompt_cn`，英文进 `prompt_en`。
   若只写中文再靠词典逐词翻译，会留下「左眉尾一道浅white旧疤」这类中英混排，
   而多数图像模型会直接忽略夹在英文里的中文片段。
"""

from __future__ import annotations

from .schema import AssetCard, StageVariables, VisualDNA

# ─────────────────────────────────────────────────────────────
# 题材预设（中英双语）—— 无 LLM 时的确定性补全依据
# 风格方向取自用户素材 §5；材质取自 §7 材质清单
# ─────────────────────────────────────────────────────────────

WORLD_PRESETS: dict[str, dict] = {
    "wasteland": {
        "hair_cn": ("及腰", "凌乱感", "深棕", "侧分", "无刘海"),
        "hair_en": ("waist-length", "messy layered", "dark brown", "side-parted",
                    "no bangs"),
        "body_cn": ("175cm", "清瘦结实", "中偏宽"),
        "body_en": ("175cm", "lean and weathered", "medium-broad"),
        "material_cn": "战术尼龙", "material_en": "tactical nylon",
        "texture_cn": "边缘磨损、织物沁入沙尘",
        "texture_en": "frayed edges, dust-impregnated weave",
        "palette_cn": "铁锈棕", "palette_en": "rust brown",
        "palette4_cn": ("铁锈棕", "暗黄", "灰绿", "枪灰色钛合金"),
        "palette4_en": ("rust brown", "ochre", "gray-green", "gunmetal titanium"),
        "outfit_cn": "多层废土生存装：破损军用风衣 + 战术背心 + 多口袋工装裤",
        "outfit_en": "layered wasteland survival gear: battered military trench coat, "
                     "tactical vest, multi-pocket cargo trousers",
        "equip_cn": ["防风护目镜（推在额头）", "腰间机械扳手", "战术背包"],
        "equip_en": ["windproof goggles pushed up on the forehead",
                     "mechanical wrench at the waist", "tactical backpack"],
        "marks_cn": ["左眉尾一道浅白旧疤"], "marks_en": ["a shallow pale scar on the left brow tail"],
    },
    "cyberpunk": {
        "hair_cn": ("短发", "高层次(蓬松动感)", "银", "偏右", "空气刘海"),
        "hair_en": ("short", "high-layered, voluminous", "silver", "right-parted",
                    "air bangs"),
        "body_cn": ("172cm", "纤细运动型", "窄肩"),
        "body_en": ("172cm", "slim athletic", "narrow-shouldered"),
        "material_cn": "碳纤维", "material_en": "carbon fiber",
        "texture_cn": "哑光复合板 + 霓虹感镶边",
        "texture_en": "matte composite panels with neon-reactive trim",
        "palette_cn": "深灰黑", "palette_en": "deep charcoal",
        "palette4_cn": ("深灰黑", "霓虹青", "品红", "镀铬金属"),
        "palette4_en": ("deep charcoal", "neon cyan", "magenta", "chrome"),
        "outfit_cn": "都市机能装：高领紧身衣 + 短款发光外套 + 硬质护膝",
        "outfit_en": "urban techwear: high-collar bodysuit, cropped light-emitting jacket, "
                     "hard-shell knee guards",
        "equip_cn": ["机械义眼（右眼）", "颈后数据接口", "电子手环"],
        "equip_en": ["cybernetic right eye", "nape data port", "electronic wristband"],
        "marks_cn": ["右眼为机械义眼，瞳孔是红色光圈"],
        "marks_en": ["right eye replaced by a cybernetic eye with a red aperture iris"],
    },
    "scifi": {
        "hair_cn": ("短发", "低层次(整齐厚重)", "黑", "中分", "无刘海"),
        "hair_en": ("short", "low-layered, neat weight", "black", "centre-parted",
                    "no bangs"),
        "body_cn": ("178cm", "高大匀称", "中肩"),
        "body_en": ("178cm", "tall and fit", "medium-shouldered"),
        "material_cn": "钛合金", "material_en": "titanium alloy",
        "texture_cn": "拉丝合金 + 哑光陶瓷嵌片",
        "texture_en": "brushed alloy with matte ceramic inserts",
        "palette_cn": "深空蓝", "palette_en": "deep space blue",
        "palette4_cn": ("深空蓝", "冷白 LED", "银", "磨砂钢"),
        "palette4_en": ("deep space blue", "cold white LED", "silver", "brushed steel"),
        "outfit_cn": "制式星际制服：高领紧身内层 + 硬质护甲外层 + 功能腰带",
        "outfit_en": "regulation starship uniform: high-collar close-fit base layer, "
                     "hard-shell armour outer layer, utility belt",
        "equip_cn": ["多功能腕甲", "通讯耳麦", "肩部识别章"],
        "equip_en": ["multi-function wrist guard", "comm headset", "shoulder insignia"],
        "marks_cn": ["左颊有制式编码烙印"], "marks_en": ["regulation code brand on the left cheek"],
    },
    "fantasy": {
        "hair_cn": ("长发", "自然卷", "金", "中分", "侧分刘海"),
        "hair_en": ("long", "naturally wavy", "blonde", "centre-parted", "side-swept bangs"),
        "body_cn": ("176cm", "修长轻盈", "中肩"),
        "body_en": ("176cm", "willowy and graceful", "medium-shouldered"),
        "material_cn": "皮革", "material_en": "leather",
        "texture_cn": "手工压纹皮革、压印符文",
        "texture_en": "hand-tooled leather with embossed runes",
        "palette_cn": "墨绿", "palette_en": "deep green",
        "palette4_cn": ("墨绿", "暗金", "米白", "做旧黄铜"),
        "palette4_en": ("deep green", "dark gold", "cream", "aged brass"),
        "outfit_cn": "旅装：亚麻内衬 + 皮质胸甲 + 长款斗篷",
        "outfit_en": "travelling attire: linen underlayer, leather cuirass, long cloak",
        "equip_cn": ["附魔佩剑", "腰间药囊", "皮质卷轴筒"],
        "equip_en": ["enchanted sword", "waist herb pouch", "leather scroll case"],
        "marks_cn": ["手背上有一道发光的铭文"],
        "marks_en": ["a faintly glowing rune inscription on the back of the hand"],
    },
    "dark_fantasy": {
        "hair_cn": ("中长发", "微卷", "银灰", "侧分", "八字刘海"),
        "hair_en": ("medium-length", "slightly wavy", "silver-gray", "side-parted",
                    "curtain bangs"),
        "body_cn": ("180cm", "清瘦但有压迫感", "宽肩"),
        "body_en": ("180cm", "gaunt but imposing", "broad-shouldered"),
        "material_cn": "人造皮革", "material_en": "faux leather",
        "texture_cn": "开裂漆面覆于暗色皮革，银质细工装饰",
        "texture_en": "cracked lacquer over dark leather, silver filigree",
        "palette_cn": "暗红", "palette_en": "dark red",
        "palette4_cn": ("暗红", "墨黑", "银白", "冷银"),
        "palette4_en": ("dark red", "ink black", "silver white", "cold silver"),
        "outfit_cn": "维多利亚式暗色长外套 + 高领蕾丝 + 束腰",
        "outfit_en": "Victorian dark long coat, high lace collar, corseted waist",
        "equip_cn": ["银制十字吊坠", "手杖（内藏细剑）"],
        "equip_en": ["silver cross pendant", "walking cane concealing a slim blade"],
        "marks_cn": ["瞳孔呈暗红色，边缘泛银"],
        "marks_en": ["dark red iris with a silver rim"],
    },
    "ancient": {
        "hair_cn": ("及腰", "直发", "墨黑", "中分", "无刘海"),
        "hair_en": ("waist-length", "straight", "ink black", "centre-parted", "no bangs"),
        "body_cn": ("174cm", "纤细轻盈", "窄肩"),
        "body_en": ("174cm", "slender and light", "narrow-shouldered"),
        "material_cn": "亚麻", "material_en": "fine woven silk",
        "texture_cn": "细密织纹、手工刺绣滚边",
        "texture_en": "fine woven texture with hand-embroidered trim",
        "palette_cn": "月白", "palette_en": "moon white",
        "palette4_cn": ("月白", "黛青", "墨黑", "旧银"),
        "palette4_en": ("moon white", "slate blue", "ink black", "antique silver"),
        "outfit_cn": "对襟长袍 + 外罩大袖 + 束腰丝带",
        "outfit_en": "front-buttoned long robe, wide-sleeved outer layer, silk waist sash",
        "equip_cn": ["布囊", "玉质发簪", "无鞘长刀"],
        "equip_en": ["cloth satchel", "jade hairpin", "unscabbarded long blade"],
        "marks_cn": ["眉心一点朱砂印记"], "marks_en": ["a cinnabar mark at the centre of the brow"],
    },
    "military": {
        "hair_cn": ("寸头", "低层次(整齐厚重)", "黑", "偏左", "无刘海"),
        "hair_en": ("buzz cut", "low-layered, neat weight", "black", "left-parted",
                    "no bangs"),
        "body_cn": ("183cm", "肌肉结实、方正", "很宽"),
        "body_en": ("183cm", "muscular and squared", "very broad-shouldered"),
        "material_cn": "凯夫拉纤维", "material_en": "Kevlar fiber",
        "texture_cn": "耐磨防撕裂织物、加固缝线",
        "texture_en": "abrasion-resistant ripstop with reinforced stitching",
        "palette_cn": "军绿", "palette_en": "army green",
        "palette4_cn": ("军绿", "泥土棕", "黑", "磨砂钢"),
        "palette4_en": ("army green", "mud brown", "black", "brushed steel"),
        "outfit_cn": "迷彩作战服 + 战术背心 + 军靴，腿部绑带固定匕首",
        "outfit_en": "camouflage fatigues, tactical vest, combat boots, leg straps "
                     "securing a dagger",
        "equip_cn": ["战术头盔", "肩部通讯电台", "大腿枪套"],
        "equip_en": ["tactical helmet", "shoulder-mounted radio", "thigh holster"],
        "marks_cn": ["右臂有部队编号纹身", "下巴有青茬"],
        "marks_en": ["unit-number tattoo on the right arm", "stubbled jaw"],
    },
    "modern": {
        "hair_cn": ("中长发", "低层次(整齐厚重)", "黑", "三七分", "侧分刘海"),
        "hair_en": ("medium-length", "low-layered, neat weight", "black", "30/70 parted",
                    "side-swept bangs"),
        "body_cn": ("170cm", "普通匀称", "中肩"),
        "body_en": ("170cm", "average build", "medium-shouldered"),
        "material_cn": "羊毛", "material_en": "woven wool",
        "texture_cn": "挺括羊毛、细微人字纹",
        "texture_en": "crisp woven wool with a subtle herringbone",
        "palette_cn": "藏青", "palette_en": "navy",
        "palette4_cn": ("藏青", "米白", "酒红", "哑光银"),
        "palette4_en": ("navy", "cream", "wine red", "matte silver"),
        "outfit_cn": "都市通勤：剪裁合体的外套 + 内搭衬衫 + 直筒长裤",
        "outfit_en": "urban commute wear: tailored overcoat, dress shirt, straight trousers",
        "equip_cn": ["皮质通勤包", "腕表"],
        "equip_en": ["leather commuter bag", "wristwatch"],
        "marks_cn": [], "marks_en": [],
    },
    "mecha": {
        "hair_cn": ("短发", "碎层次(随性时尚)", "金", "二八分", "眉上刘海"),
        "hair_en": ("short", "choppy layered", "blonde", "20/80 parted", "above-brow bangs"),
        "body_cn": ("176cm", "精干结实", "中肩"),
        "body_en": ("176cm", "compact athletic", "medium-shouldered"),
        "material_cn": "铝合金", "material_en": "airframe aluminium alloy",
        "texture_cn": "拉丝机身合金 + 警示标贴",
        "texture_en": "brushed airframe alloy with warning decals",
        "palette_cn": "高饱和红", "palette_en": "high-saturation red",
        "palette4_cn": ("高饱和红", "白", "金属灰", "镀铬金属"),
        "palette4_en": ("high-saturation red", "white", "metallic gray", "chrome"),
        "outfit_cn": "紧身驾驶战斗服（红白配色）+ 部队徽章 + 神经链接头环",
        "outfit_en": "skin-tight pilot suit in red and white, unit emblem, "
                     "neural-link head ring",
        "equip_cn": ["头环式神经传感器", "胸前部队徽章", "腰部应急拉环"],
        "equip_en": ["head-ring neural sensor", "chest unit emblem", "waist emergency pull"],
        "marks_cn": ["颈侧有接口式神经端子"],
        "marks_en": ["port-type neural terminals on the side of the neck"],
    },
    "western_fantasy": {
        "hair_cn": ("中短发", "大卷", "棕", "偏左", "无刘海"),
        "hair_en": ("medium-short", "loose curls", "brown", "left-parted", "no bangs"),
        "body_cn": ("179cm", "壮实宽阔", "宽肩"),
        "body_en": ("179cm", "sturdy and broad", "broad-shouldered"),
        "material_cn": "皮革", "material_en": "oiled leather",
        "texture_cn": "上油皮革覆于锁甲，板甲有凹陷",
        "texture_en": "oiled leather over chainmail, dented plate armour",
        "palette_cn": "深棕", "palette_en": "deep brown",
        "palette4_cn": ("深棕", "旧金", "灰蓝", "做旧黄铜"),
        "palette4_en": ("deep brown", "antique gold", "slate blue", "aged brass"),
        "outfit_cn": "骑士装：锁甲内衬 + 板甲外覆 + 皮质腰带 + 破损披风",
        "outfit_en": "knightly harness: chainmail underlayer, plate armour, leather belt, "
                     "battered cloak",
        "equip_cn": ["双手长剑", "圆盾", "挎包"],
        "equip_en": ["two-handed longsword", "round shield", "shoulder satchel"],
        "marks_cn": ["左肩有一枚家族纹章烙痕"],
        "marks_en": ["a family-crest brand on the left shoulder"],
    },
    "steampunk": {
        "hair_cn": ("中长发", "中卷", "铜红", "侧分", "龙须刘海"),
        "hair_en": ("medium-length", "medium curls", "copper red", "side-parted",
                    "tendril bangs"),
        "body_cn": ("173cm", "精瘦", "中肩"),
        "body_en": ("173cm", "wiry", "medium-shouldered"),
        "material_cn": "黄铜", "material_en": "polished brass",
        "texture_cn": "抛光黄铜、外露铆钉与铜管",
        "texture_en": "polished brass with visible rivets and copper piping",
        "palette_cn": "古铜", "palette_en": "antique bronze",
        "palette4_cn": ("古铜", "深棕", "暗绿", "黄铜"),
        "palette4_en": ("antique bronze", "deep brown", "dark green", "brass"),
        "outfit_cn": "工装礼服：马甲 + 衬衫 + 皮质护臂 + 齿轮装饰腰带",
        "outfit_en": "engineer's formal wear: waistcoat, shirt, leather bracers, "
                     "gear-adorned belt",
        "equip_cn": ["单边护目镜（可翻下）", "机械手", "蒸汽压力表"],
        "equip_en": ["monocle goggles (flip-down)", "mechanical hand", "steam pressure gauge"],
        "marks_cn": ["右手为黄铜机械义手"],
        "marks_en": ["right hand replaced by a brass mechanical prosthetic"],
    },
}

GENERIC_PRESET = {
    "hair_cn": ("中长发", "低层次(整齐厚重)", "黑", "中分", "无刘海"),
    "hair_en": ("medium-length", "low-layered, neat weight", "black", "centre-parted",
                "no bangs"),
    "body_cn": ("172cm", "匀称", "中肩"),
    "body_en": ("172cm", "fit", "medium-shouldered"),
    "material_cn": "棉", "material_en": "woven cotton",
    "texture_cn": "干净织物", "texture_en": "clean woven textile",
    "palette_cn": "深灰黑", "palette_en": "deep charcoal",
    "palette4_cn": ("深灰黑", "暗红", "冷白", "枪灰色钛合金"),
    "palette4_en": ("deep charcoal", "dark red", "cool white", "gunmetal titanium"),
    "outfit_cn": "内层 + 外层 + 腰带的三层功能服装",
    "outfit_en": "three-layer functional outfit: base layer, outer layer, utility belt",
    "equip_cn": ["一件与身份匹配的标志物"],
    "equip_en": ["one signature item matching the character's role"],
    "marks_cn": [], "marks_en": [],
}

# 题材 → 面部骨相（中英）
FACE_BY_WORLD = {
    "wasteland": (("棱角分明、饱经风霜", "方下颌、脸颊凹陷"),
                  ("angular, weathered", "strong jaw, hollow cheeks")),
    "cyberpunk": (("锐利精致", "高颧骨、下颌线清晰"),
                  ("sharp, refined", "high cheekbones, defined jaw")),
    "ancient": (("柔和鹅蛋", "下颌柔和、轮廓温婉"),
                ("soft oval", "delicate jaw, gentle contour")),
    "military": (("方正硬朗", "重下颌、眉骨平"),
                 ("square, solid", "heavy jaw, flat brow ridge")),
    "fantasy": (("修长鹅蛋", "下颌柔和、眉骨略高"),
                ("slender oval", "soft jaw, high brow")),
    "dark_fantasy": (("瘦削锐利", "颧骨突出、下颌锋利"),
                     ("gaunt, sharp", "prominent cheekbones, sharp jaw")),
}
FACE_DEFAULT = (("鹅蛋", "均衡下颌"), ("oval", "balanced jaw"))


def preset_for(world: str) -> dict:
    return WORLD_PRESETS.get(world) or GENERIC_PRESET


def _set_if_empty(dc, fld: str, val) -> bool:
    """只在字段为空时写入 —— 兑现「不覆盖用户已给内容」。"""
    cur = getattr(dc, fld, None)
    if cur in ("", None, [], ()):
        setattr(dc, fld, val)
        return True
    return False


# ─────────────────────────────────────────────────────────────
# 补全
# ─────────────────────────────────────────────────────────────

def complete(card: AssetCard, parsed, rules, llm=None) -> tuple[AssetCard, list[str]]:
    """补全角色卡。返回 (card, 补全说明列表)。"""
    notes: list[str] = []
    vd: VisualDNA = card.visual_dna
    sv: StageVariables = card.stage_variables
    p = preset_for(card.world or parsed.world)

    # ⓪ **用户明确给的**身份信息 —— 必须先落到卡上（此前的 bug：被整段丢掉）
    if parsed.age and _set_if_empty(card, "age", parsed.age):
        notes.append(f"年龄：{parsed.age}（用户指定）")
    if parsed.gender and _set_if_empty(card, "gender", parsed.gender):
        notes.append(f"性别：{parsed.gender}（用户指定）")
    if parsed.occupation and _set_if_empty(card, "occupation", parsed.occupation):
        notes.append(f"身份：{parsed.occupation}（用户指定）")
    if parsed.world and _set_if_empty(card, "world", parsed.world):
        notes.append(f"世界观风格：{parsed.world}（用户指定）")

    if parsed.no_auto_complete:
        notes.append("⚠️ 用户要求「不要自动补全」→ 只保留已给信息 + 最小必需项")
        _set_if_empty(vd, "face_shape", "oval")
        _set_if_empty(vd, "eye_shape", "almond")
        _set_if_empty(vd, "eye_color", "dark brown")
        _set_if_empty(vd, "hair_color", "black")
        _set_if_empty(vd, "hair_length", "medium-length")
        _set_if_empty(vd, "body_type", "fit")
        _set_if_empty(vd, "primary_color", "dark gray")
        _set_if_empty(vd, "material", "cotton")
        return card, notes

    # ① 面部（中英分别写，英文直接取英文预设，不留中英混排）
    face_cn, face_en = FACE_BY_WORLD.get(card.world, FACE_DEFAULT)
    _set_if_empty(vd, "face_shape", face_cn[0])
    _set_if_empty(vd, "jaw", face_cn[1])
    vd.face_shape_en = vd.face_shape_en or face_en[0]
    vd.jaw_en = vd.jaw_en or face_en[1]
    _set_if_empty(vd, "brow_ridge", "适中、略突出")
    vd.brow_ridge_en = vd.brow_ridge_en or "moderate, slightly prominent"
    _set_if_empty(vd, "nose_bridge", "挺直")
    vd.nose_bridge_en = vd.nose_bridge_en or "straight"
    _set_if_empty(vd, "lips", "轮廓清晰、薄至中等")
    vd.lips_en = vd.lips_en or "defined, thin-to-medium"
    _set_if_empty(vd, "eye_shape", "狭长杏眼")
    vd.eye_shape_en = vd.eye_shape_en or "narrow almond"
    _set_if_empty(vd, "eye_color", "深褐")
    vd.eye_color_en = vd.eye_color_en or "dark brown"

    # ② 固定特征（身份锁，必须填）
    ff = card.fixed_features
    _set_if_empty(ff, "core_bone_structure", f"{card.world or '通用'}骨相")
    flex = {"wasteland": "wasteland bone structure", "cyberpunk": "cyberpunk bone structure",
            "ancient": "soft oriental bone structure", "military": "solid square bone structure"}
    ff.core_bone_structure_en = getattr(ff, "core_bone_structure_en", "") or \
        flex.get(card.world, "generic bone structure")
    _set_if_empty(ff, "facial_contour", f"{face_cn[0]}、{face_cn[1]}")
    ff.facial_contour_en = getattr(ff, "facial_contour_en", "") or \
        f"{face_en[0]}, {face_en[1]}"
    _set_if_empty(ff, "iris_color", vd.eye_color)
    if not ff.permanent_marks:
        ff.permanent_marks = list(p["marks_cn"])
        ff.permanent_marks_en = list(p["marks_en"])
        if ff.permanent_marks:
            notes.append(f"永久识别点：{len(ff.permanent_marks)} 处（跨镜识别锚点）")
    if not ff.signature_micro_expressions:
        ff.signature_micro_expressions = ["轻微眯眼（思考时）", "单侧嘴角先动（笑时）"]
        ff.signature_micro_expressions_en = ["slight squint when thinking",
                                             "one-sided mouth corner moves first when smiling"]
    if not ff.body_fixed_habit_moves:
        ff.body_fixed_habit_moves = ["左手拇指按压物件"]
        ff.body_fixed_habit_moves_en = ["presses objects with the left thumb"]
    _set_if_empty(ff, "voice_base_timbre", "中低音、偏冷" if card.gender == "male" else "中音、清冷")
    _set_if_empty(ff, "voice_speed", "偏慢")

    # ③ 发型 / 体型 / 服装 / 材质 / 配色（中英成对写入）
    h_cn, h_en = p["hair_cn"], p["hair_en"]
    b_cn, b_en = p["body_cn"], p["body_en"]
    for fld, cn, en in (("hair_length", h_cn[0], h_en[0]),
                        ("hair_volume", h_cn[1], h_en[1]),
                        ("hair_color", h_cn[2], h_en[2]),
                        ("hair_parting", h_cn[3], h_en[3]),
                        ("bangs", h_cn[4], h_en[4]),
                        ("height", b_cn[0], b_en[0]),
                        ("body_type", b_cn[1], b_en[1]),
                        ("shoulder_width", b_cn[2], b_en[2]),
                        ("primary_color", p["palette_cn"], p["palette_en"]),
                        ("material", p["material_cn"], p["material_en"]),
                        ("surface_texture", p["texture_cn"], p["texture_en"])):
        _set_if_empty(vd, fld, cn)
        setattr(vd, fld + "_en", getattr(vd, fld + "_en", "") or en)

    _set_if_empty(vd, "hair_style", "自然")
    vd.hair_style_en = vd.hair_style_en or "natural"
    _set_if_empty(vd, "silhouette", "层次清晰、一眼可辨")
    vd.silhouette_en = vd.silhouette_en or "layered, readable at a glance"
    _set_if_empty(vd, "layers", p["outfit_cn"])
    vd.layers_en = vd.layers_en or p["outfit_en"]
    _set_if_empty(sv, "full_outfit", p["outfit_cn"])
    _set_if_empty(sv, "skin_state", "自然、有风吹日晒质感")
    sv.skin_state_en = getattr(sv, "skin_state_en", "") or \
        "natural, weather-exposed, realistic skin texture"
    _set_if_empty(sv, "physique_vibe", "沉稳、警觉")
    sv.physique_vibe_en = getattr(sv, "physique_vibe_en", "") or "composed, alert"

    # ④ 装备（用户明确给的机械部件**不得丢**）
    equip_cn = [e.strip() for e in p["equip_cn"] if e.strip()] + list(parsed.equipment_hints)
    equip_en = list(p["equip_en"]) + [_equip_en(e) for e in parsed.equipment_hints]
    if equip_cn:
        _set_if_empty(vd, "signature_accessory", "；".join(dict.fromkeys(equip_cn)))
        sv.core_accessories = sv.core_accessories or vd.signature_accessory
    if equip_en:
        vd.signature_accessory_en = vd.signature_accessory_en or \
            ", ".join(dict.fromkeys([e for e in equip_en if e]))
        sv.core_accessories_en = sv.core_accessories_en or vd.signature_accessory_en
    for e in parsed.equipment_hints:
        if e not in vd.signature_points:
            vd.signature_points.append(e)
    vd.signature_points_en = [_equip_en(x) for x in vd.signature_points]

    # ⑤ 用户指定材质优先（不覆盖）
    if parsed.material_hints:
        vd.material = "、".join(parsed.material_hints)
        vd.material_en = ", ".join(_material_en(m) for m in parsed.material_hints)
        notes.append(f"⚠️ 采用用户指定材质：{vd.material}")

    if _set_if_empty(vd, "primary_color", p["palette_cn"]):
        notes.append(f"配色四层：主 {p['palette4_cn'][0]} / 辅 {p['palette4_cn'][1]} / "
                     f"点缀 {p['palette4_cn'][2]} / 金属 {p['palette4_cn'][3]}")
    vd.palette4_en = p["palette4_en"]

    # ⑥ 锁定策略 —— ⚠️ **不在此处设**：原写法 `["FACE","HAIR","BODY"]` 正是
    #    `ASSET_CARD.yaml` 第 104 行**注释里的举例**（把文档举例当默认值），
    #    且 HAIR 不在 §四·补 A（头发可改）、真正不可改的瞳色反而漏了。
    #    现统一由 `lock.default_locks/default_editable`（依 §四·补 A/B）在
    #    `agent._create` 一处设置 —— 6 个 agent 各写一套必然发散。

    # ⑦ 可选 LLM 精修
    if llm is not None and getattr(llm, "available", False):
        try:
            llm_enrich(card, parsed, llm)
            notes.append("已用 LLM 精修视觉描述")
        except Exception as e:
            notes.append(f"⚠️ LLM 精修失败，保留规则补全结果：{e}")

    return card, notes


# ── 术语英译兜底（用户给的零散中文部件）──

_EQUIP_EN = {
    "机械左臂": "cybernetic left arm", "机械右臂": "cybernetic right arm",
    "机械手臂": "cybernetic arm", "机械腿": "cybernetic leg",
    "机械右腿": "cybernetic right leg", "机械左腿": "cybernetic left leg",
    "机械义眼": "cybernetic eye", "义眼": "artificial eye", "义肢": "prosthetic limb",
    "军靴": "combat boots", "护目镜": "goggles", "面具": "face mask",
    "头盔": "helmet", "背包": "backpack", "枪套": "holster", "匕首": "dagger",
    "佩剑": "sword", "手杖": "cane", "护甲": "armor", "肩甲": "pauldron",
    "披风": "cape", "项链": "necklace", "戒指": "ring", "腰带": "belt",
    "手套": "gloves", "斗篷": "cloak",
}
_MAT_EN = {"棉": "cotton", "亚麻": "linen", "牛仔": "denim", "皮革": "leather",
           "人造皮革": "faux leather", "防水织物": "waterproof fabric",
           "战术尼龙": "tactical nylon", "凯夫拉纤维": "Kevlar fiber",
           "碳纤维": "carbon fiber", "钛合金": "titanium alloy",
           "铝合金": "aluminium alloy", "磨砂钢": "brushed steel",
           "镀铬金属": "chrome", "黄铜": "brass", "铜": "copper", "陶瓷": "ceramic",
           "玻璃": "glass", "亚克力": "acrylic", "橡胶": "rubber", "硅胶": "silicone",
           "毛皮": "fur", "羽毛": "feather", "木材": "wood", "石材": "stone",
           "魔法晶体": "magic crystal", "生物组织": "biological tissue"}


def _equip_en(zh: str) -> str:
    """把用户给的装备词译成英文（含「左/右」侧位）。"""
    if zh in _EQUIP_EN:
        return _EQUIP_EN[zh]
    for k, v in sorted(_EQUIP_EN.items(), key=len, reverse=True):
        if k in zh:
            side = ""
            if "左" in zh:
                side = "left "
            elif "右" in zh:
                side = "right "
            return v.replace(" ", f" {side}", 1) if side else v
    return zh


def _material_en(zh: str) -> str:
    return _MAT_EN.get(zh, zh)


def build_card(parsed, asset_id: str, now: str) -> AssetCard:
    return AssetCard(
        id=asset_id, type="character",
        name=parsed.name or (parsed.raw[:16] if parsed.raw else "character"),
        source=parsed.raw, created_at=now, updated_at=now,
        age=parsed.age, gender=parsed.gender, occupation=parsed.occupation,
        world=parsed.world,
    )


LLM_SYSTEM = """你是 AI 漫剧的视觉资产设定师。给你一个角色卡（JSON）与用户原始描述，
请**只补全空白字段**，不要改动任何已有非空值。
所有 *_en 字段必须是纯英文；对应中文 *_cn 字段必须是中文（不要混排）。
必须遵守三视图硬标准：同一角色，面部/发型/体型/服装/配色/材质跨视图一致。
返回与输入同结构的 JSON。"""


def llm_enrich(card: AssetCard, parsed, llm) -> None:
    """用 LLM 精修仍为空的视觉字段（不覆盖已有非空值）。"""
    import json as _json
    payload = card.to_dict()
    user = (f"用户原始描述：{parsed.raw}\n\n"
            f"当前角色卡：\n{_json.dumps(payload, ensure_ascii=False)}\n\n"
            f"请补全 visual_dna / fixed_features / stage_variables 中的空白项。")
    out = llm.complete_json(LLM_SYSTEM, user)
    new = AssetCard.from_dict(payload)
    for k, v in (out or {}).items():
        if isinstance(v, dict) and hasattr(new, k):
            for kk, vv in v.items():
                sub = getattr(new, k)
                if hasattr(sub, kk):
                    setattr(sub, kk, vv)
    for fl in (f.name for f in VisualDNA.__dataclass_fields__.values()):
        if not getattr(card.visual_dna, fl) and getattr(new.visual_dna, fl):
            setattr(card.visual_dna, fl, getattr(new.visual_dna, fl))
