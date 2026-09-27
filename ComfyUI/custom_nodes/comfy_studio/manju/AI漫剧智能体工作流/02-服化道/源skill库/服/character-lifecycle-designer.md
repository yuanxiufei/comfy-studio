---
name: character-lifecycle-designer
display_name: 剧本角色全生命周期高级AI肖像生成系统
description: 实现「剧本输入→角色提取→性格侧写→基础档案→跨阶段一致性造型设计→Markdown文档→多风格AI肖像+三视图」全流程闭环。核心特性：全节点强制确认机制、终身固定核心识别特征库确保跨阶段100%视觉一致性。
trigger: 用户上传剧本文本或输入触发词【启动角色全生命周期设计】
---

> **本文解决的问题**：V2.0 规格 §29 只说"角色成长要新建状态卡 `Character_001_State_A`"，但**未定义什么是不变的、什么是可变的**。本 skill 用「终身固定核心识别特征库」给出了明确边界。

# 剧本角色全生命周期高级AI肖像生成系统

## 核心目标

实现剧本角色从解析到 AI 肖像生成的完整闭环，确保同一角色**跨年龄、跨阶段、跨场景**的视觉高度统一。

## 触发条件

- 用户上传/粘贴完整剧本文本
- 用户输入触发词：`【启动角色全生命周期设计（分步确认版）】`

---

## 全局铁则（最高优先级）

### 1. 全节点强制确认规则
- 每个生成环节必须执行「生成 → 发起强制确认 → 用户确认 → 推进流程」
- 未收到用户明确的「确认」指令，流程必须暂停
- **禁止自动推进、跳步、批量生成**

### 2. 跨阶段一致性绝对规则
- 【终身固定核心识别特征库】是同一角色所有造型/肖像的**唯一铁则**
- 核心固定特征 **100% 不可改动**，仅可调整剧情适配变量项
- 杜绝"换脸式"偏差

### 3. 剧本唯一依据规则
- 所有内容必须严格锚定用户提供的剧本原文
- 禁止脱离剧本世界观进行无依据编造

### 4. 无限修改规则
- 用户任何环节提出修改，必须立即响应
- 修改后重新生成并再次确认，直至用户满意

---

## 六阶段执行流程

### 第一阶段：剧本解析与角色提取

**执行步骤：**
1. 接收完整剧本文本
2. 自动过滤场景描述、镜头语言、旁白、音效、环境标注等**非角色内容**
3. 精准识别提取所有有效角色（有台词、关键动作、推动剧情）
4. 剔除仅单次出场、无台词、无剧情作用的背景路人/群演
5. 统计每个角色的出场次数、台词句数、戏份占比
6. 划分角色层级：主角 / 核心配角 / 次要配角 / 客串
7. 为每个角色提取关键节点：
   - **年龄变化节点**：少年期、青年期、中年期、老年期
   - **剧情发展阶段**：初始状态、成长转折期、巅峰期、低谷期、结局状态
   - **特殊状态节点**：日常、战斗、落魄、黑化等

**输出格式：**

```markdown
## 角色统计与关键节点清单

| 角色名称 | 角色层级 | 出场次数 | 台词句数 | 戏份占比 | 核心剧情作用 | 关键节点清单 |
|---|---|---|---|---|---|---|
| XX | 主角 | XX次 | XX句 | XX% | 主线核心承载者 | 1.少年期(8岁,拜师); 2.青年期(20岁,下山)... |
```

**强制确认话术（原样输出）：**
```
请您核对上述角色统计清单与对应关键剧情节点清单，可选择以下操作：
回复【确认】：清单无误，进入下一环节
回复具体修改意见：包括增删角色、调整角色层级、增删/修改角色关键节点，我将调整后重新生成清单，再次发起确认
⚠️ 未收到您的明确确认指令，流程不会自动推进
```

---

### 第二阶段：角色深度性格侧写

**执行规则：**
- 严格按角色优先级，**单个角色逐个生成**
- 单角色确认完毕后再生成下一个
- **禁止一次性生成所有角色的侧写**

**单角色侧写六维度：**
1. **核心性格矩阵**：显性特质、隐性特质、核心性格标签
2. **底层行为逻辑**：核心欲望、核心恐惧、终身行为底层动机
3. **分阶段性格变化**：对应关键节点的性格转变、核心驱动事件
4. **性格成因**：剧本内铺垫的性格形成关键事件
5. **剧情核心矛盾**：内在自我矛盾 + 与剧情/其他角色的外在冲突
6. **人物成长弧线完整路径**

> 每个性格特质必须**标注对应的剧本情节支撑**。

---

### 第三阶段：基础角色档案构建

**执行规则：**
- 单个角色逐个推进
- **单个维度逐个确认**
- 禁止一次性生成单个角色的全维度档案，也禁止一次性生成多个角色的档案

**11 个核心维度（固定顺序）：**

| # | 维度 | 内容 |
|---|---|---|
| 1 | **姓名** | 本名、别名、昵称、称号 |
| 2 | **年龄** | 全生命周期核心年龄区间，标注外貌年龄与心理年龄差异 |
| 3 | **【核心】终身固定核心识别特征库** | **核心骨相 / 五官轮廓 / 瞳色 / 标志性永久识别点（胎记、疤痕、齿型）/ 终身不变的微表情习惯** |
| 4 | **基础外貌特征** | 基准状态（剧本开篇）的面部细节、身高身形、皮肤质感、发型发色、基础体态 |
| 5 | **性格特质** | 基于确认后的性格侧写凝练 |
| 6 | **背景经历** | 原生背景、成长关键节点、前置关联 |
| 7 | **人物弧线** | 对应关键节点的完整转变路径 |
| 8 | **角色定位** | 剧情功能定位、核心叙事作用 |
| 9 | **声音特点** | 全生命周期基础音色、分阶段声线变化、语速、语癖、口音 |
| 10 | **肢体语言** | 终身固定习惯动作、分阶段体态变化、微表情特点 |
| 11 | **基准服装风格** | 剧本开篇初始状态的日常穿搭、标志性基础穿搭 |

**单维度确认话术（含跳过保护）：**
```
请您核对【XX角色】的【XX维度】设计方案，可选择以下操作：
回复【确认】：内容无误，进入下一个维度的设计
回复具体修改意见：我将调整后重新生成该维度方案，再次发起确认
回复【跳过】：确认跳过该维度（我将先提示该维度对AI视频创作的价值，二次确认后再执行跳过）
⚠️ 未收到您的明确确认指令，流程不会自动推进
```

---

### 第四阶段：分阶段/分场景一致性造型设计

**单阶段造型方案结构：**

```markdown
## 【XX角色-XX阶段/XX状态造型方案】

### 1. 阶段基础信息
- 对应剧本剧情节点：XXX
- 年龄区间：XXX
- 核心场景：XXX
- 角色状态：XXX

### 2. 【强制固定项】
100%沿用【XX角色终身固定核心识别特征库】全部内容，无任何改动：
- 核心骨相：XXX
- 五官轮廓：XXX
- 瞳色：XXX
- 标志性永久识别点：XXX
- 终身微表情习惯：XXX

### 3. 【剧情适配变量项】
仅调整符合本阶段/本状态的可变特征：

**外貌变化**：皮肤状态 / 皱纹老化痕迹 / 发色变化 / 胡须毛发变化 / 伤病痕迹
**体态变化**：身形变化 / 体态气质
**发型妆容**：发型 / 妆容
**服装配饰**：全套穿搭 / 核心配饰

### 4. 适配核心场景
本造型对应的剧本核心出场场景：XXX
```

---

### 第五阶段：标准化 Markdown 文档整合输出

```markdown
# 《【剧本全称】》角色全生命周期全维度设计档案

## 一、剧本基础信息
- 剧本名称 / 剧本类型 / 时长集数 / 有效角色总数

## 二、核心角色与关键节点最终确认清单

## 三、分角色基础档案与终身固定特征库

### 角色1：XXX
1. 基础信息
2. 终身固定核心识别特征库（全阶段强制遵循）
3. 基准外貌特征
4. 性格特质
5. 背景经历
6. 完整人物弧线
7. 声音特点
8. 肢体语言
9. 基准服装风格
10. 深度性格侧写（含分阶段变化）

## 四、分角色全阶段/全场景一致性造型设计方案
```

---

### 第六阶段：多风格 AI 全身肖像与三视图生成

**执行规则：** 风格先确认 → 基准肖像先生成并确认 → 分阶段肖像逐个生成并确认。**禁止一次性生成所有内容。**

**第一步：风格选择与确认（5 种）**
```
1. 专业大师级高精度写实风格（电影质感）
2. 中国风3D电影质感
3. 油画风格（古典艺术）
4. 赛博朋克（科幻未来）
5. 二维中国风动画电影风格
```

**第二步：基准肖像生成与一致性锁定**

用户确认风格后，按角色优先级先生成**基准状态（剧本开篇初始状态）**的套图：
- 1 张 8K 超高清全身肖像主图
- 1 套同形象标准三视图（正面全身、45° 半侧面全身、正侧面全身）

**生成铁则：** 100% 严格遵循终身固定核心识别特征库；8K 超高清、无 AI 畸变、无结构错误。

**第三步：分阶段套图生成与确认**

- 每套图 = 1 张 8K 全身肖像主图 + 1 套同形象三视图
- **一致性铁则**：核心固定特征 100% 与已确认的基准肖像一致；仅调整变量项；同一角色的所有套图，**光影风格、渲染质感、画幅比例完全统一**

---

## 分风格精准生成指令（5 组）

### 1. 专业大师级高精度写实（电影质感）
```
Hollywood cinematic full-body portrait, ultra-realistic digital human rendering,
professional studio lighting, photorealistic skin texture with pores and subtle imperfections,
detailed hair strands with natural flow, fabric wrinkles and material details accurately rendered,
natural color grading, soft bokeh background, subject-centered composition,
character appearance strictly matching the reference profile, precise body proportions,
8K resolution, no AI artifacts or anatomical errors, film grain texture, cinematic color science
```

### 2. 中国风 3D 电影质感
```
Chinese 3D animated film style full-body portrait, PBR physically based rendering,
Eastern aesthetic standards, soft and delicate lighting, authentic traditional Chinese
costume details with intricate patterns, realistic material textures for silk and fabric,
precise body proportions, no visual distortions, production quality matching top-tier
Chinese 3D animated films, 8K resolution
```

### 3. 油画风格（古典艺术）
```
Renaissance to Neoclassical master oil painting style full-body portrait, visible canvas texture,
natural artistic brushstrokes, Rembrandt lighting technique, rich and heavy color palette,
accurate and expressive character portrayal matching the reference profile,
world-class classical oil painting quality, no structural errors or distortions, 8K resolution
```

### 4. 赛博朋克（科幻未来）
```
Hollywood sci-fi cyberpunk aesthetic full-body portrait, neon light atmosphere,
futuristic tech elements strictly matching character setting, rich image layers,
strong color contrast, full-body details maximized, precise body proportions,
no AI artifacts or anatomical errors, top-tier sci-fi film visual standards, 8K resolution
```

### 5. 二维中国风动画电影风格
```
Top-tier Chinese 2D animated film style full-body portrait, clean and fluid traditional
Chinese linework, classical Chinese color palette system, Eastern aesthetic character design,
delicate and natural brushwork, rich image layers, no jagged edges or distortions,
precise body proportions, character design strictly matching the reference profile,
8K resolution
```

---

## 异常处理机制

| 情况 | 处理 |
|---|---|
| **剧本格式异常** | 明确告知缺失信息，引导补充；**不得擅自编造角色、剧情与节点** |
| **请求跳过维度/阶段** | 先提示该维度对 AI 视频创作与一致性生成的价值，**二次确认后**方可跳过 |
| **AI 肖像一致性偏差** | 严格按已确认的基准肖像与固定特征库重新生成；**不得擅自调整人设** |
| **用户长时间未回复** | 流程持续暂停，不自动关闭或推进；定期提示完成确认 |

---

## 与本项目 V2.0 规格的映射

**本文是 §29「角色成长规则」与 §28「多集漫剧规则」的完整实现方法。**

| 本文机制 | V2.0 规格对应 |
|---|---|
| **终身固定核心识别特征库** | **§29 的判定边界**（规格说"新建状态卡"，本文件明确哪些特征 100% 不可动） |
| 核心骨相 / 五官轮廓 / 瞳色 / 永久识别点 / 终身微表情 | §05.2 FACE DNA + SIGNATURE DNA 的"不可变"部分 |
| **剧情适配变量项** | §29 的"受伤/换发型/换服装/成长/衰老"等变化项 |
| 基准肖像 → 分阶段套图 | §29 的 `Character_001_State_A / _State_B / _State_C` 生成顺序 |
| 「所有套图光影/质感/画幅完全统一」 | §28 跨集 `LOCK_LIGHTING` / `LOCK_COLOR` |
| 11 维度档案（固定顺序） | §05.1 人物信息的 25 个字段（本文件整理为 11 个维度组） |
| 声音特点 / 肢体语言维度 | **规格未覆盖**，可补充到 ASSET_CARD（对接 `05-音乐音频` 配音选角） |
| 全节点强制确认 | 与 `02-服化道` 主控的"每步暂停等确认"一致，本文件话术更严格 |
| 跳过保护（二次确认） | 与规格 §42「必须先列出将变化的锁定项再执行」同源 |

### 建议的落地动作

1. **在 `ASSET_CARD.yaml` 中拆分特征为两组**：
   - `fixed_features`（终身固定，对应 LOCK_FACE 的不可变部分）
   - `stage_variables`（剧情适配变量，对应各 `_State_X` 的差异项）
2. **在 §29 的执行流程中明确顺序**：先出基准态 → 用户确认 → 再出各阶段态（避免各阶段同时生成导致漂移）
3. **补充两个规格未覆盖的维度到资产卡**：`voice`（音色/语速/语癖）与 `body_language`（固定习惯动作）——这两个直接影响配音与视频生成
