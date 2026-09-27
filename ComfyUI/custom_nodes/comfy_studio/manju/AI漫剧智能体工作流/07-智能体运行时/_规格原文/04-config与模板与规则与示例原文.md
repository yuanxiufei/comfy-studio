# config.json

```json
{
  "agent_name": "AI漫剧资产库角色道具智能体",
  "version": "1.0.0",
  "language": {
    "input": ["zh-CN", "en", "mixed"],
    "prompt_default": "en"
  },
  "asset_types": [
    "character",
    "character_three_view",
    "portrait",
    "costume",
    "equipment",
    "prop"
  ],
  "default_character_layout": {
    "canvas": "16:9",
    "orientation": "landscape",
    "left_panel": "portrait_or_head_detail",
    "right_panel": "front_side_back_full_body",
    "background": "white_or_very_light_gray"
  },
  "default_render": {
    "quality": "8K",
    "style": "photorealistic_high_definition_character_design",
    "lighting": "soft_even_studio_lighting",
    "shadow": "soft_subtle"
  },
  "three_view": {
    "front": "strict_front_view",
    "side": "strict_90_degree_side_view",
    "back": "strict_back_view",
    "pose": "neutral_standing_pose",
    "consistency": true
  },
  "auto_completion": true,
  "preserve_user_constraints": true,
  "output_full_prompt_after_generation": true
}
```

---

# PROMPT_TEMPLATE.md

## Character Asset Prompt

```text
Create a professional 16:9 landscape character design sheet for a cinematic AI animation / game production asset library.

CHARACTER:
[character identity]

AGE:
[age]

GENDER:
[gender]

PERSONALITY AND PRESENCE:
[personality and visual presence]

FACE:
[face shape, facial features, skin tone, distinctive features]

EYES:
[eye shape, color, expression]

HAIR:
[hairstyle, length, color, texture]

BODY:
[height, body type, proportions, physical condition]

CLOTHING:
[complete layered clothing structure]

MATERIALS:
[precise material descriptions]

EQUIPMENT:
[weapons, armor, tools, accessories and their exact positions]

COLOR PALETTE:
[primary color, secondary color, accent color, metal color]

POSE:
[neutral standing pose]

LAYOUT:

LEFT SIDE:
A large front-facing half-body portrait or detailed head-and-shoulders close-up of the exact same character, emphasizing facial identity, skin texture, eyes, hairstyle, clothing details and material quality.

RIGHT SIDE:
Three full-body views of the exact same character arranged horizontally:

1. STRICT FRONT VIEW
2. STRICT 90-DEGREE SIDE VIEW
3. STRICT BACK VIEW

The three views must show exactly the same character with identical body proportions, facial identity, hairstyle, clothing, equipment, accessories, colors and materials.

Do not redesign the character between views.

COMPOSITION:
Clean professional character design sheet, balanced spacing, clear separation between the portrait and the three full-body views, full body visible from head to feet, no cropped limbs.

BACKGROUND:
Pure white or extremely light gray studio background, no environmental scene.

LIGHTING:
Soft, even studio lighting, subtle ambient illumination, soft contact shadows, no dramatic hard shadows.

STYLE:
Ultra-detailed photorealistic cinematic character concept art, professional game character design sheet, high-end visual development artwork, realistic materials, sharp clothing construction, highly readable equipment details.

QUALITY:
8K ultra-high-definition detail, extremely clean rendering, high material fidelity, precise anatomy, consistent character identity.

NEGATIVE PROMPT:
extra fingers, extra limbs, missing limbs, duplicated character, duplicate equipment, inconsistent clothing, inconsistent hairstyle, inconsistent proportions, incorrect side view, incorrect back view, three-quarter view, distorted anatomy, malformed hands, deformed face, cropped head, cropped feet, random weapons, random accessories, floating objects, text, logo, watermark, UI, background clutter, dramatic hard shadows
```

---

# CHARACTER_RULES.md

## Character Consistency

同一个角色的不同视图必须保持：

```text
Face
Hair
Body
Age
Clothing
Accessories
Equipment
Colors
Materials
Proportions
```

完全一致。

---

## Clothing Hierarchy

服装按照：

```text
Base Layer
↓
Middle Layer
↓
Outer Layer
↓
Armor / Protection
↓
Waist Equipment
↓
Leg Equipment
↓
Boots
↓
Accessories
```

描述。

---

## Color Hierarchy

建议：

```text
Primary Color
Secondary Color
Accent Color
Metal Color
```

避免随机配色。

---

## Material Hierarchy

不要只描述颜色。

应该描述：

```text
Color
+
Material
+
Surface Finish
+
Wear
+
Texture
```

例如：

```text
matte black tactical nylon,
reinforced stitching,
subtle fabric texture,
slightly worn edges,
low-reflective surface
```

---

# EXAMPLES.md

## Example 01

### User

```text
一个30岁的废土女佣兵，机械左臂，穿旧军用风衣
```

### Agent 应理解为

```text
角色：
30岁女性废土佣兵

视觉方向：
写实、废土、军事、电影感

需要自动补全：
面部
发型
体型
军用风衣结构
机械左臂
腰部装备
腿部装备
靴子
磨损
配色
材质
```

最终生成标准三视图资产 Prompt。

---

## Example 02

### User

```text
赛博朋克女医生，银色短发
```

Agent 应保留：

```text
女性医生
赛博朋克
银色短发
```

然后自动补全：

```text
年龄
面部
体型
未来医疗服装
医疗设备
赛博义体
配色
材质
装备
```

---

## Example 03

### User

```text
把刚才角色的衣服改成白色
```

Agent：

只修改：

```text
Clothing Color
```

其他内容保持不变。

---

## Example 04

### User

```text
设计一把未来主义能源步枪
```

自动切换：

```text
PROP ASSET MODE
```

生成：

```text
主视图
+
结构细节
+
正面
+
侧面
+
背面
```

并保持：

```text
尺寸一致
结构一致
材质一致
颜色一致
```

---

# Agent Execution Flow

```text
USER INPUT
    ↓
INTENT PARSING
    ↓
ASSET TYPE DETECTION
    ↓
CHARACTER / PROP / COSTUME
    ↓
AUTO COMPLETION
    ↓
DESIGN STANDARDIZATION
    ↓
MATERIAL DESIGN
    ↓
COLOR SYSTEM
    ↓
EQUIPMENT CONSISTENCY
    ↓
THREE-VIEW COMPOSITION
    ↓
PROMPT GENERATION
    ↓
IMAGE GENERATION
    ↓
FULL PROMPT OUTPUT
```

---

# Final Principle

这个 Agent 的核心不是：

```text
“描述一个人物”
```

而是：

```text
“建立一个可以持续用于 AI 漫剧生产的标准化视觉资产。”
```