# EXPRESSION & POSE LIBRARY — 表情与动作库

> 对应规格 §10｜EXPRESSION ENGINE + §11｜POSE ENGINE
>
> **素材来源**：
> - 基线 16 式表情英文列 ← `源skill库/服/character-model-sheet.md`（源 skill 原 12 式，补齐至 16）
> - **扩展 50 式表情** ← 用户素材 `data/资料/…/50种人物面部表情AI提示词.xlsx`（中文公式为源原文，英文为本项目补充）
> - 表情集网格布局 ← 同上源 skill

---

## 一、表情库（§10）

本库分两级使用：

| 级 | 数量 | 要求 | 用途 |
|---|---|---|---|
| **基线** | **16 式** | 核心角色**必须全部建立** | 覆盖情绪大类，构成角色的表情底盘 |
| **扩展** | **50 式** | 按族**按需选用** | 细粒度情绪变体（笑有 5 种、哭有 5 种…） |

---

### 1.1 基线 16 式（核心角色必建）

**英文描述词列**提炼自 `源skill库/服/character-model-sheet.md`（该源 skill 只列 12 式，此处补齐 16 式并统一措辞）。

| # | 中文 | 眉 | 眼 | 嘴 | 面部肌肉要点 | 英文描述词 | 状态 |
|---|---|---|---|---|---|---|---|
| 1 | 平静 | 自然微平 | 直视，瞳孔放松 | 轻闭 | 无张力 | `neutral expression, relaxed features, steady gaze, soft relaxed eyebrows` | ☐ |
| 2 | 微笑 | 微扬 | 眼尾微收 | 嘴角上扬 | 颊肌轻提 | `subtle smile, gently upturned mouth corners, slight eye narrowing, soft gaze` | ☐ |
| 3 | 喜悦 | 上扬 | 弯眼，卧蚕明显 | 张口笑 | 苹果肌隆起 | `joyful expression, bright eyes, cheerful smile, raised cheeks, upturned mouth corners, relaxed eyebrows` | ☐ |
| 4 | 愤怒 | 紧压下压 | 瞪大，瞳孔收紧 | 咬紧/上唇提 | 眉间竖纹 | `angry expression, furrowed brows, narrowed eyes, tense jaw, flushed face` | ☐ |
| 5 | 悲伤 | 内端上挑 | 下垂，眼圈泛红 | 嘴角下拉 | 下唇微颤 | `sad expression, downcast eyes, downturned mouth, melancholic, drooping eyebrows` | ☐ |
| 6 | 惊讶 | 高扬 | 睁大，瞳孔放大 | 圆张 | 额头横纹 | `surprised expression, wide eyes, raised eyebrows, open mouth, shocked` | ☐ |
| 7 | 恐惧 | 上提紧锁 | 极大睁开 | 半张僵硬 | 面部僵硬发白 | `fearful expression, wide eyes with whites showing, raised eyebrows, tense mouth, terrified` | ☐ |
| 8 | 怀疑 | 单侧上挑 | 眯眼 | 嘴角单侧下压 | 一侧颊肌紧 | `suspicious expression, one raised eyebrow, narrowed eyes, tightened mouth` | ☐ |
| 9 | 轻蔑 | 单侧高挑 | 眼睑下压俯视 | 单侧嘴角上提 | 下巴微抬 | `contemptuous expression, half-lidded eyes, one-sided mouth corner raised, raised chin` | ☐ |
| 10 | 羞涩 | 平缓 | 视线下移躲闪 | 抿唇 | 双颊潮红 | `shy expression, blushing cheeks, downcast eyes, slight smile, looking away` | ☐ |
| 11 | 冷笑 | 单侧挑 | 冷光，眼睑半垂 | 单侧上扬 | 无笑意肌群 | `cold smirk, one-sided mouth corner raised, half-lidded eyes, unamused eyes` | ☐ |
| 12 | 忍泪 | 内端紧压 | 湿润，极力上抬 | 紧抿下压 | 下颌紧绷 | `holding back tears, glistening eyes, pressed inner eyebrows, tightened lips, tense jaw` | ☐ |
| 13 | 震惊 | 高扬 | 瞳孔骤缩 | 僵张 | 全部肌肉僵直 | `shocked expression, wide eyes, constricted pupils, rigid facial muscles, open mouth, stunned` | ☐ |
| 14 | 强装镇定 | 刻意放平 | 视线微移 | 强行平直 | 颈肌紧、吞咽动作 | `forced calm, deliberately relaxed eyebrows, slightly averted gaze, tight neck, swallowing` | ☐ |
| 15 | 准备反击 | 压低 | 聚焦锁定 | 紧抿 | 咬肌隆起 | `determined expression, focused intense gaze, pressed lips, tightened masseter` | ☐ |
| 16 | 崩溃 | 完全塌下 | 失焦/闭眼 | 张口失控 | 面部溶解感 | `breakdown expression, collapsed eyebrows, unfocused or closed eyes, uncontrolled open mouth, emotional collapse` | ☐ |

### 1.2 扩展 50 式（按 8 族分组，按需选用）

> **来源**：用户素材 `data/资料/1014 AI动漫制作/04AI视频-视频成片/50种人物面部表情AI提示词.xlsx`（**工作区外，不随本库分发**；等价副本在 `data/资料/AI漫剧素材/04AI视频/`）。
> 表中「**精准描述公式**」为**源素材原文**——它把情绪拆成了可执行的面部动作 + 光影 + 色调，是可直接进步骤词的写法。
> 「**英文**」列为**本项目补充**（源素材仅中文），可与基线 16 式的英文列混用。
>
> **用法**：先看基线 16 式是否够用；需要**细分**时（如"笑"要区分元气/温柔/苦笑/假笑/腹黑）从下面对应族里取。
> 单角色**不建议超过 20 式**——表情过多会稀释角色辨识度。

#### 🟡 喜乐族（13）

| # | 表情 | 精准描述公式 | 英文 |
|---|---|---|---|
| 1 | 元气微笑 | 嘴角上扬至颧骨，苹果肌饱满，露 6-8 颗牙齿，眼尾弯成月牙，瞳孔明亮，日系动漫风，柔和光影 | `energetic smile, mouth corners lifted to cheekbones, plump cheeks, 6-8 teeth showing, crescent smiling eyes, bright pupils, anime style, soft lighting` |
| 2 | 大笑 | 嘴角咧至耳根，露整排牙齿，眼角笑出细纹，鼻翼微张，头微仰，元气满满，明亮色调 | `laughing out loud, mouth ear to ear, full row of teeth, crow's feet at eye corners, slightly flared nostrils, head tilted back, bright vibrant tones` |
| 3 | 偷笑 | 嘴角抿起上扬，脸颊鼓起，眼神狡黠，目光躲闪，手掌轻捂嘴，低饱和度色调 | `suppressed giggle, pressed upturned lips, puffed cheeks, sly eyes, averted gaze, hand covering mouth, low saturation` |
| 4 | 害羞笑 | 嘴角轻扬，脸颊泛红，耳朵发红，头微低，眼神低垂，睫毛轻颤，柔和柔光 | `bashful smile, slight upturn of mouth, flushed cheeks, reddened ears, head lowered, downcast eyes, fluttering eyelashes, soft light` |
| 5 | 温柔浅笑 | 嘴角轻弯，眼尾下垂带暖意，瞳孔柔和，目光平视，周身有柔和光晕，暖色调 | `gentle soft smile, softly curved mouth, warm drooping eye corners, tender pupils, level gaze, soft halo, warm tones` |
| 6 | 宠溺笑 | 嘴角弯成弧形，眼尾带笑意，瞳孔温柔，目光注视前方，暖黄色光影 | `affectionate smile, arched mouth, smiling eye corners, tender pupils, forward gaze, warm yellow lighting` |
| 7 | 得意笑 | 嘴角上扬，挑眉，眼神得意，头微抬，双手抱胸，高光打在面部 | `smug smile, upturned mouth, raised eyebrow, self-satisfied eyes, chin lifted, arms crossed, highlight on face` |
| 8 | 得意挑眉 | 眉峰上扬，嘴角上扬，眼神得意，头微抬，双手抱胸，高光 | `smug raised eyebrow, arched brow, upturned mouth, self-satisfied gaze, chin lifted, arms crossed, highlight` |
| 9 | 调皮眨眼 | 单眼眨动，嘴角上扬，眼神狡黠，头微歪，暖色调光影 | `playful wink, one eye closed, upturned mouth, mischievous gaze, head tilted, warm lighting` |
| 10 | 期待睁眼 | 眼睛睁大，瞳孔明亮，眼神期待，嘴角上扬，头微抬，暖色调 | `expectant wide eyes, bright pupils, hopeful gaze, upturned mouth, chin lifted, warm tones` |
| 11 | 满足喟叹 | 嘴角弯成弧形，眼神满足，头微仰，呼出一口气，柔和光影 | `contented sigh, arched mouth, satisfied eyes, head tilted back, exhaling, soft lighting` |
| 12 | 恍然大悟 | 眼睛睁大，瞳孔明亮，眉头舒展，嘴角上扬，手拍额头，暖色调 | `sudden realization, wide bright eyes, relaxed brows, upturned mouth, hand to forehead, warm tones` |
| 13 | 好奇歪头 | 头微歪，眼睛睁大，眼神好奇，瞳孔明亮，嘴角微扬，柔和光影 | `curious head tilt, wide eyes, inquisitive gaze, bright pupils, slight smile, soft lighting` |

#### 🔵 悲苦族（8）

| # | 表情 | 精准描述公式 | 英文 |
|---|---|---|---|
| 14 | 苦笑 | 嘴角扯出僵硬弧度，眉头微蹙，眼神无奈，眼底带疲惫，面部肌肉紧绷，低饱和色调 | `bitter smile, stiff mouth arc, slightly furrowed brows, resigned eyes, tired eyes, tense facial muscles, low saturation` |
| 15 | 委屈瘪嘴 | 嘴角下撇，下唇外翻，眼眶泛红，鼻头微红，头微低，眼神委屈，柔和阴影 | `aggrieved pout, downturned mouth corners, everted lower lip, reddened eye rims, red nose tip, head lowered, wronged gaze, soft shadows` |
| 16 | 小声抽泣 | 嘴角下撇，泪珠挂睫，鼻翼翕动，肩膀微抖，头微低，冷色调 | `quiet sobbing, downturned mouth corners, tears on eyelashes, quivering nostrils, trembling shoulders, head lowered, cool tones` |
| 17 | 放声大哭 | 嘴巴大张，眼泪直流，眉头紧锁，肩膀剧烈抖动，头微仰，高对比度光影 | `crying loudly, mouth wide open, streaming tears, tightly knitted brows, violently shaking shoulders, head tilted back, high contrast lighting` |
| 18 | 隐忍落泪 | 嘴角抿紧，眼眶泛红，泪珠在眼眶打转，眼神倔强，下颌紧绷，侧光 | `holding back tears, pressed lips, reddened eye rims, tears welling up, stubborn gaze, clenched jaw, side light` |
| 19 | 啜泣 | 嘴角微颤，泪珠滑落脸颊，鼻头通红，眼神低垂，低饱和色调 | `sniffling weep, slightly trembling mouth, tears rolling down cheeks, red nose, downcast eyes, low saturation` |
| 20 | 失落低头 | 头微低，眼神黯淡，嘴角下撇，肩膀微垂，低饱和色调 | `dejected, head lowered, dim eyes, downturned mouth corners, slumped shoulders, low saturation` |
| 21 | 疲惫耷拉眼 | 眼皮下垂，眼神疲惫，眼袋明显，嘴角下撇，头微低，低饱和色调 | `exhausted drooping eyes, heavy eyelids, weary gaze, visible eye bags, downturned mouth, head lowered, low saturation` |

#### 🔴 愤怒与坚毅族（5）

| # | 表情 | 精准描述公式 | 英文 |
|---|---|---|---|
| 22 | 愤怒瞪眼 | 眉头倒竖，眼睛圆睁，瞳孔收缩，鼻翼扩张，咬牙切齿，面部青筋微露，冷硬光影 | `angry glare, brows inverted, wide open eyes, constricted pupils, flared nostrils, gritted teeth, visible facial veins, cold hard lighting` |
| 23 | 暴躁怒吼 | 嘴巴大张，眉头紧锁，眼神凶狠，头发微炸，拳头紧握，强烈明暗对比 | `furious roar, mouth wide open, tightly knitted brows, ferocious gaze, bristling hair, clenched fists, strong chiaroscuro` |
| 24 | 愠怒皱眉 | 眉峰凸起，嘴角下撇，眼神不悦，下颌紧绷，面部肌肉僵硬，侧光 | `sullen frown, raised brow ridge, downturned mouth, displeased gaze, clenched jaw, stiff facial muscles, side light` |
| 25 | 坚定眼神 | 眼神锐利，眉头舒展，嘴角抿紧，下颌微抬，目光平视前方，强烈明暗对比 | `determined gaze, sharp eyes, relaxed brows, pressed lips, chin lifted, level forward stare, strong chiaroscuro` |
| 26 | 决绝皱眉 | 眉头紧锁，眼神决绝，嘴角抿成直线，下颌紧绷，侧光 | `resolute frown, tightly knitted brows, unwavering gaze, lips pressed into a line, clenched jaw, side light` |

#### 🟣 嘲弄与心机族（6）

| # | 表情 | 精准描述公式 | 英文 |
|---|---|---|---|
| 27 | 傲娇冷笑 | 嘴角单侧上扬，眉峰微挑，眼神轻蔑，下颌微抬，侧脸角度，冷色调 | `tsundere smirk, one-sided mouth corner raised, arched brow, contemptuous gaze, chin lifted, three-quarter view, cool tones` |
| 28 | 冷笑嘲讽 | 嘴角单侧上扬，眼神轻蔑，眉峰微挑，下颌微抬，冷色调 | `mocking sneer, one-sided mouth corner raised, contemptuous eyes, arched brow, chin lifted, cool tones` |
| 29 | 不屑撇嘴 | 嘴角下撇，眉峰上挑，眼神不屑，头微侧，低饱和光影 | `disdainful sneer, downturned mouth corner, raised brow, dismissive gaze, head turned aside, low saturation lighting` |
| 30 | 假笑 | 嘴角上扬无笑意，眼神空洞，苹果肌僵硬，眉峰平直，面部表情不自然，冷光 | `fake smile, upturned mouth without warmth, empty eyes, stiff cheeks, flat brows, unnatural expression, cold light` |
| 31 | 腹黑笑 | 嘴角单侧上扬，眼神深邃带算计，眉峰微挑，冷色调 | `scheming smile, one-sided mouth corner raised, deep calculating eyes, arched brow, cool tones` |
| 32 | 傲娇扭头 | 头微扭，嘴角下撇，眼神傲娇，眉峰微挑，侧脸角度，冷光 | `tsundere head turn, head turned aside, downturned mouth corner, haughty eyes, arched brow, profile view, cold light` |

#### 🟠 惊讶与茫然族（5）

| # | 表情 | 精准描述公式 | 英文 |
|---|---|---|---|
| 33 | 惊讶瞪眼 | 眉毛上扬，眼睛圆睁，嘴巴微张呈"O"型，瞳孔放大，眼神茫然，顶光 | `surprised wide eyes, raised eyebrows, round open mouth, dilated pupils, blank gaze, top light` |
| 34 | 错愕失神 | 眼睛睁大，眼神空洞，嘴巴微张，面部表情呆滞，头微歪，柔和阴影 | `stunned blankness, wide eyes, vacant gaze, slightly open mouth, dazed expression, head tilted, soft shadows` |
| 35 | 震惊捂嘴 | 眼睛圆睁，瞳孔放大，手捂嘴，身体微僵，眼神震惊，高对比度 | `shocked hand over mouth, wide open eyes, dilated pupils, hand covering mouth, frozen posture, shocked gaze, high contrast` |
| 36 | 意外挑眉 | 眉峰上扬，眼睛微睁，嘴角微张，眼神意外，柔和光影 | `surprised eyebrow raise, arched brow, slightly widened eyes, parted lips, taken-aback gaze, soft lighting` |
| 37 | 茫然发呆 | 眼神涣散，嘴巴微张，头微低，瞳孔失焦，面部无表情，低饱和色调 | `dazed spacing out, unfocused eyes, slightly open mouth, head lowered, defocused pupils, blank expression, low saturation` |

#### ⚫ 冷漠与疏离族（5）

| # | 表情 | 精准描述公式 | 英文 |
|---|---|---|---|
| 38 | 高冷面无表情 | 嘴角平直，眉头舒展，眼神淡漠，下颌线清晰，面部无多余表情，冷色调 | `aloof deadpan, flat mouth line, relaxed brows, indifferent gaze, defined jawline, expressionless face, cool tones` |
| 39 | 慵懒淡漠 | 眼皮半耷拉，眼神慵懒，嘴角平直，头微歪，周身散发慵懒气息，暖光 | `languid indifference, half-lidded eyes, lazy gaze, flat mouth, head tilted, indolent aura, warm light` |
| 40 | 疏离冷漠 | 眼神冰冷，嘴角平直，眉头微蹙，下颌微抬，侧脸角度，冷硬光影 | `distant coldness, icy gaze, flat mouth, slightly furrowed brows, chin lifted, three-quarter view, cold hard lighting` |
| 41 | 困倦打哈欠 | 嘴巴大张，眼皮耷拉，眼神惺忪，眼角泛红，头微仰，柔和暖光 | `sleepy yawn, mouth wide open, drooping eyelids, drowsy gaze, reddened eye corners, head tilted back, soft warm light` |
| 42 | 疑惑皱眉 | 眉头紧锁，眼睛微眯，眼神疑惑，嘴角下撇，手托下巴，侧光 | `puzzled frown, tightly knitted brows, narrowed eyes, questioning gaze, downturned mouth, hand on chin, side light` |

#### 🟢 恐惧与紧张族（3）

| # | 表情 | 精准描述公式 | 英文 |
|---|---|---|---|
| 43 | 紧张抿唇 | 嘴唇抿成直线，眉头微蹙，眼神紧张，瞳孔收缩，手指紧握，冷硬光影 | `nervous pressed lips, lips in a tight line, slightly furrowed brows, tense gaze, constricted pupils, clenched fingers, cold hard lighting` |
| 44 | 害怕缩肩 | 眼睛圆睁，瞳孔放大，眉头紧锁，身体缩起，肩膀内扣，冷色调 | `fearful cowering, wide eyes, dilated pupils, tightly knitted brows, hunched body, shoulders drawn in, cool tones` |
| 45 | 恐惧瞪眼 | 眼睛圆睁，眼神惊恐，嘴巴微张，面部苍白，身体微颤，顶光 | `terrified wide eyes, wide open eyes, horrified gaze, slightly open mouth, pale face, trembling body, top light` |

#### 🩷 羞怯与娇憨族（5）

| # | 表情 | 精准描述公式 | 英文 |
|---|---|---|---|
| 46 | 害羞脸红 | 脸颊通红，耳朵发红，头微低，眼神躲闪，嘴角抿起，柔和柔光 | `blushing shyness, flushed red cheeks, reddened ears, head lowered, averted gaze, pressed lips, soft light` |
| 47 | 尴尬挠头 | 脸颊微红，眼神尴尬，嘴角扯出僵硬弧度，手挠头，暖色调 | `awkward head scratch, slightly flushed cheeks, embarrassed gaze, stiff mouth arc, scratching head, warm tones` |
| 48 | 撒娇嘟嘴 | 嘴巴嘟起，脸颊鼓起，眼神委屈带期待，头微歪，暖色调光影 | `coquettish pout, pursed protruding lips, puffed cheeks, aggrieved yet expectant gaze, head tilted, warm lighting` |
| 49 | 温柔注视 | 眼神柔和，瞳孔明亮，嘴角轻扬，目光注视前方，暖光 | `tender gaze, soft eyes, bright pupils, gently upturned mouth, forward gaze, warm light` |
| 50 | 宠溺摸头 | 嘴角弯成弧形，眼神温柔，目光注视下方，手抬起，暖黄色光影 | `affectionate head pat, arched mouth, tender eyes, downward gaze, hand raised, warm yellow lighting` |

### 1.3 表情集图布局（来源：`源skill库/服/character-model-sheet.md`）

| 表情数量 | 网格布局 |
|---|---|
| 4 种 | 2×2 |
| 8 种 | 2×4 或 4×2 |
| 16 种（基线全量） | 4×4 |
| **25 种** | 5×5 |
| **50 种（扩展全量）** | 5×10 或 7×8（建议分批出，单图超 25 格会糊） |

**表情集提示词：**
```
, expression sheet, facial expressions, close-up portraits, {expression_list},
grid layout, consistent character, clean white background
```

### 1.4 选用建议（避免"表情堆砌"）

| 情形 | 建议 |
|---|---|
| 常规角色 | **基线 16 式**足够 |
| 主角 / 核心反派（戏份多、情绪层次要求高） | 基线 16 + 从扩展库挑 **8-16 式**（按角色气质选族：冷感角色多取「冷漠/嘲弄」族，病娇多取「嘲弄/悲苦」族） |
| 群像配角 | 只需 **4-6 式**（基线里挑常用） |
| 上限 | **单角色不超过 20 式**——过多会稀释辨识度，也增加出图成本与一致性风险 |

> ⚠️ 无论选多少式，**同一角色必须始终用同一套**——中途换表情集会导致脸型漂移。

### 铁律（§10）

**只允许改变：** 眉 · 眼 · 嘴 · 面部肌肉 · 微表情

**绝不允许改变：**
- 脸型
- 年龄
- 发型
- 发色
- 核心身份

> 表情图的 prompt 必须把 `FACE/HAIR/BODY/AGE` 写入 Consistency Constraints，把 `EXPRESSION` 写入 MODIFY 位。

---

## 二、动作库（§11）

### 基础动作（18 种）

| # | 动作 | 关键要点 | 服装限制注意 | 状态 |
|---|---|---|---|---|
| 1 | 站立 | 重心分布、肩线水平 | 长袍下摆自然垂坠 | ☐ |
| 2 | 行走 | 步幅、手臂反向摆动 | 裙摆/披风动势 | ☐ |
| 3 | 奔跑 | 前倾角度、腾空瞬间 | 衣料飞起方向 | ☐ |
| 4 | 坐 | 脊椎曲线、腿部叠放 | 下摆铺展 | ☐ |
| 5 | 跪 | 膝盖着地角度 | 膝部布料压痕 | ☐ |
| 6 | 躺 | 身体轴线、头部转向 | 衣料贴合 | ☐ |
| 7 | 转身 | 腰部带动、发丝惯性 | 披风离心 | ☐ |
| 8 | 回头 | 颈肩分离、视线落点 | 发丝甩动 | ☐ |
| 9 | 抬手 | 肩胛联动、指节形态 | 袖口变形 | ☐ |
| 10 | 拔武器 | 握持方式、手腕角度 | 肩甲限制 | ☐ |
| 11 | 持物 | 握持姿势与道具 ID 对应 | 手部与道具比例 | ☐ |
| 12 | 拥抱 | 双方重心、臂围合度 | 双人衣料交叠 | ☐ |
| 13 | 对峙 | 距离、视线、对称/失衡 | 武器指向 | ☐ |
| 14 | 防御 | 护住重心、格挡点 | 护具受力面 | ☐ |
| 15 | 攻击 | 发力链（脚→腰→肩→手） | 动作幅度受服装限制 | ☐ |
| 16 | 跌倒 | 失衡瞬间、支撑点 | 衣料撕裂可能 | ☐ |
| 17 | 扶墙 | 手部接触点、身体倾斜 | 墙面材质对应 | ☐ |
| 18 | 回眸 | 头肩扭转极限、眼神 | 发丝弧线 | ☐ |

### 动作必须符合（§11）

1. **人体结构** — 关节活动范围正确
2. **重心** — 有真实支撑点与重心线
3. **力学** — 发力链合理
4. **角色身份** — 姿态气质与身份匹配（贵族/武士/平民不通用）
5. **服装限制** — 长袍不能做紧身裤动作，重甲不能灵活翻滚
6. **道具使用方式** — 握持方式与 PROP 资产卡记录一致

### 动作 prompt 追加负面词

```
broken limbs, reversed joints, extra arms, unbalanced center of gravity, floating
肢体断裂, 关节反向, 多余手臂, 重心失衡, 悬浮
```

---

## 三、表情/动作产线规范

### 表情图（Expression Sheet）
- 结构：同一角色 16 网格（4×4）或按需子集
- 一致性锚点必须写满：`FACE / HAIR / AGE / SKIN TONE / EYE COLOR`
- 只改眉/眼/嘴/肌肉
- 负面词追加：`changed face shape, changed age, changed ethnicity, collapsed facial structure, deformed eyes`

### 动作图（Pose Sheet）
- 结构：同一角色多动作并排
- 服装状态必须与当前剧情阶段一致（对应 `CST_00X_状态`）
- 道具必须引用 PROP ID
- 负面词追加：见上

---

## 四、与剧情情绪照明联动

表情的情绪基调应与 05-风格光影 的情绪照明公式一致：

| 表情 | 建议光影 |
|---|---|
| 愤怒 / 准备反击 | 伦勃朗光 + 强阴影，低角仰拍 |
| 悲伤 / 忍泪 | 侧逆光 + 柔光，浅景深 |
| 恐惧 / 震惊 | 顶光或冷调背光，高对比 |
| 羞涩 / 微笑 | 柔和正面光，暖调 |
| 轻蔑 / 冷笑 | 单侧分割光，冷调 |
| 崩溃 | 阴影笼罩，前景虚化 |
