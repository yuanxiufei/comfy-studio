---
name: character-model-sheet
display_name: 角色设定表生成器（无文字标注版）
description: 帮助用户生成专业角色三视图，左侧主图展示角色全身三视角，右侧边缘展示配饰细节和表情特写，无任何文字标注
---

> **本文解决的问题**：V2.0 规格 §06 要求"无文字/无字母/无 Logo"，但**未给出强制屏蔽文字的提示词写法**。本 skill 提供了带权重的完整方案。

# 角色设定表生成器

## 技能目标

生成无文字标注的专业角色设定图，左侧主区展示角色三视图，右侧边缘展示配饰细节和表情变化。

---

## 核心提示词模板

### 基础三视图模板

**正向提示词 (Positive Prompt)：**

```
Masterpiece, best quality, official art, character concept art, character model sheet,
character reference sheet, multiple views, (front view, side profile view, back view:1.3),
full body standing, neutral pose, clear details, clean solid white background, flat lighting,
NO TEXT, no annotations, no labels, no words, {character_description}
```

**反向提示词 (Negative Prompt)：**

```
(text, font, letters, words, annotations, labels, descriptions, dimensions, handwriting,
chart, arrows, indicators, view labels, front view text, side view text, back view text,
any text:1.8), signature, watermark, username, logo, speech bubble, messy background,
extra limbs, bad anatomy, missing fingers, cropped, blurry
```

### 执行细节（四个关键点）

1. **强化文字屏蔽**：反向提示词中 `(any text:1.8)` 赋予**超高权重**，完全禁止生成任何文字
2. **画幅比例**：建议超宽幅 **21:9** 或 **2:1**，左侧容纳三视图，右侧留空给细节特写
3. **光照**：`flat lighting` 确保受光均匀，便于观察
4. **背景**：`clean solid white background` 纯白色背景

---

## 布局结构（左主右辅）

```
[三视图主区域 - 占约 65%] [细节特写区域 - 占约 35%]
```

**左侧主区域**：角色全身正面 / 全身侧面 / 全身背面

**右侧边缘区域**：配饰特写（武器、饰物、道具）/ 服装细节（纹理、材质）/ 面部表情特写

---

## 扩展提示词

### 配饰细节特写（追加）

```
, accessory details on right side, weapon close-up, jewelry details,
costume texture details, prop showcase, arranged on right edge
```

### 表情特写集（追加）

```
, facial expression variations on right side, expression sheet,
(happy face, angry face, sad face, surprised face:1.2), arranged on right edge,
consistent character face
```

### 完整版（三视图 + 配饰 + 表情）

**正向：**
```
Masterpiece, best quality, official art, character concept art, character model sheet,
multiple views, (front view, side profile view, back view:1.3), full body standing,
neutral pose, clear details, clean solid white background, flat lighting, NO TEXT,
no annotations, {character_description}, accessory details on right side, weapon close-up,
costume texture details, facial expression variations on right side,
(happy face, angry face, sad face, excited face:1.2), arranged on right edge, consistent character
```

**反向：**
```
(text, font, letters, words, annotations, labels, descriptions, dimensions, handwriting,
chart, arrows, indicators, view labels, any text, watermark:1.8), signature, username,
logo, speech bubble, messy background, extra limbs, bad anatomy, missing fingers, cropped, blurry
```

---

## 注意事项

- **无文字原则**：所有生成的图像不应包含任何文字标注
- **左右分区**：左侧主区展示角色本体，右侧展示细节
- **风格一致性**：右侧边缘内容必须与主角色保持同一风格
- **画幅建议**：21:9 或 2:1 获得最佳布局

---

# 参考文件（内嵌）

## 一、角色风格示例库（8 种）

| 风格 | 适用 | 提示词示例 | 关键词 |
|---|---|---|---|
| **写实** | 真人影视、写实游戏 | `a young martial artist, traditional wuxia outfit, black hair tied in ponytail, determined eyes, athletic build, detailed fabric texture, realistic skin texture, cinematic lighting` | realistic skin texture / detailed fabric texture / cinematic lighting / photorealistic / lifelike proportions |
| **日式动漫** | 动画、漫画、二次元游戏 | `a teenage girl, school uniform, long flowing hair, large expressive eyes, anime art style, cel shaded, vibrant colors, clean line art` | anime art style / cel shaded / vibrant colors / clean line art / large expressive eyes |
| **美式卡通** | 卡通动画、儿童内容 | `a young adventurer, colorful outfit, exaggerated proportions, big eyes, cartoon style, smooth shading, expressive features, bright colors` | cartoon style / exaggerated proportions / smooth shading / bright colors |
| **像素艺术** | 复古/独立游戏 | `a knight in armor, pixel art style, 16-bit, limited color palette, retro game aesthetic, crisp pixels` | pixel art style / 8-bit / 16-bit / retro game aesthetic |
| **厚涂** | 奇幻插画、概念艺术 | `a mysterious mage, elaborate robes, glowing magical accessories, painterly style, oil painting texture, dramatic lighting, rich colors, brush strokes visible, fantasy art` | painterly style / oil painting texture / brush strokes visible / rich colors |
| **3D 渲染** | 3D 游戏、CG 动画 | `a sci-fi soldier, futuristic armor, helmet, 3D rendered, octane render, unreal engine, subsurface scattering, PBR materials, studio lighting` | 3D rendered / octane render / unreal engine / subsurface scattering / PBR materials |
| **水彩** | 文艺向、治愈系 | `a gentle florist, soft pastel clothing, watercolor style, soft edges, bleeding colors, paper texture, delicate, dreamy atmosphere` | watercolor style / soft edges / bleeding colors / paper texture / delicate |
| **赛博朋克** | 科幻、未来题材 | `a cyberpunk hacker, neon-lit jacket, augmented reality glasses, glowing tattoos, tech wear, neon accents, dark background with neon lights, futuristic` | cyberpunk / neon accents / tech wear / augmented reality / futuristic |

---

## 二、人物表情模板库（12 种）

> ✅ **已提炼**：本节内容已并入 `../../../引擎/EXPRESSION-POSE-LIBRARY.md` §一（扩展为 16 式并补齐英文描述词）。
> 日常请用引擎文件，本节仅作来源留存。

### 基础表情集（4 种）

| 表情 | 描述词 | 面部特征 |
|---|---|---|
| **喜** | `smiling face, happy expression, bright eyes, cheerful, joyful, upturned mouth corners, relaxed eyebrows` | 嘴角上扬 / 眼微眯或明亮 / 眉放松或微扬 |
| **怒** | `angry expression, furrowed brows, narrowed eyes, tense jaw, frowning, intense gaze, flushed face` | 眉紧锁 / 眼神锐利眯眼 / 嘴角下压紧抿 / 肌肉紧绷 |
| **哀** | `sad expression, downcast eyes, downturned mouth, teary eyes, melancholic, sorrowful, drooping eyebrows` | 眼神向下或含泪 / 嘴角下垂 / 眉呈"八"字 |
| **乐** | `excited expression, wide eyes, open mouth, laughing, overjoyed, energetic, sparkling eyes, raised eyebrows` | 眼睁开 / 嘴张开大笑 / 眉上扬 |

### 扩展表情集（8 种）

| # | 表情 | 描述词 |
|---|---|---|
| 5 | **惊讶** | `surprised expression, wide eyes, raised eyebrows, open mouth, shocked, amazed, stunned look` |
| 6 | **恐惧** | `fearful expression, wide eyes with whites showing, raised eyebrows, tense mouth, terrified, anxious, defensive posture` |
| 7 | **厌恶** | `disgusted expression, wrinkled nose, raised upper lip, narrowed eyes, displeased, contemptuous, scrunched face` |
| 8 | **困惑** | `confused expression, tilted head, furrowed brows, questioning look, puzzled, uncertain, one eyebrow raised` |

### 高级表情集（12 种）

| # | 表情 | 描述词 |
|---|---|---|
| 9 | **害羞** | `shy expression, blushing cheeks, downcast eyes, slight smile, embarrassed, flustered, looking away` |
| 10 | **自信** | `confident expression, slight smirk, determined eyes, raised chin, proud, self-assured, commanding presence` |
| 11 | **疲惫** | `tired expression, drooping eyelids, dull eyes, slack jaw, exhausted, weary, dark circles under eyes` |
| 12 | **专注** | `focused expression, intense gaze, slightly furrowed brows, pursed lips, concentrated, determined, serious` |

### 表情集布局建议

| 表情数量 | 网格布局 |
|---|---|
| 4 种 | 2×2 |
| 8 种 | 2×4 或 4×2 |
| 12 种 | 3×4 或 4×3 |

**表情集提示词格式：**
```
, expression sheet, facial expressions, close-up portraits, {expression_list},
grid layout, consistent character, clean white background
```

**示例（4 种基础表情）：**
```
Masterpiece, best quality, character expression sheet, multiple expressions,
close-up portraits, (happy, angry, sad, excited:1.2), grid layout,
consistent character, clean white background
```

---

## 与本项目 V2.0 规格的映射

| 本文机制 | V2.0 规格对应 |
|---|---|
| `(any text:1.8)` 超高权重屏蔽 | **§00 RULE-005「默认禁止图像文字」的强制实现手法**（规格只说禁止，未给权重写法） |
| `clean solid white background` + `flat lighting` | §06 的"纯白背景 / 柔和均匀光 / 无明显阴影" |
| 21:9 左主右辅布局 | §06 的"左侧放大头部细节 / 右侧三视图"（本 skill 为另一种布局：左侧三视图 / 右侧细节） |
| `consistent character` + 视图权重 `:1.3` | §18 三视图一致性 / §22 三视图负面词 |
| 8 种风格示例库 | §04.1 `visual_style` 可选值 + §49 风格具体化 |
| 12 种表情模板 | §10 的 16 表情（本库 12 种，**可作为 §10 的英文描述词补充**） |
| 表情集 2×2 / 3×4 网格 | §10 表情图产线规范 |

### 实用提示

**两种三视图布局的取舍：**

| 布局 | 来源 | 特点 |
|---|---|---|
| 左侧头部特写 + 右侧三视图 | 规格 §06（权威） | 侧重面部识别 |
| 左侧三视图 + 右侧配饰/表情（65:35） | 本 skill | 侧重信息量（一图含配饰与表情） |

**建议**：角色定妆用规格 §06 的标准；需要一次性给全信息（含配饰与表情）时用本 skill 的 21:9 布局。
