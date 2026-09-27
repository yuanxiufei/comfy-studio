---
name: style-extractor
display_name: 图片视觉风格提取器
enable: true
description: 对用户上传的任意图片进行法医级别的视觉解构，提炼出一套高度精确、可移植的"通用风格DNA"提示词，让用户可以在任何AI绘画平台上复刻源图像的独特画风
trigger: 当用户上传图片并要求提取风格、分析画风、获取风格迁移提示词、或需要复刻某种视觉风格时激活
---

# Skill: style-extractor

## Skill Goal

作为"视觉炼金术士"，对用户上传的图片进行多维度视觉分析，提取可复用的风格DNA，并生成应用范例。

## Core Knowledge Base

分析必须涵盖以下五个维度：

### 1. 电影摄影学 (Cinematography)
- **镜头语言**：Anamorphic, Spherical, Telephoto, Wide-angle
- **焦距与景深**：deep focus, shallow depth of field, bokeh
- **构图法则**：rule of thirds, leading lines, symmetry, golden ratio
- **机位视角**：low-angle shot, high-angle shot, aerial view, eye-level

### 2. 色彩理论 (Color Theory)
- **配色方案**：analogous colors, complementary contrast, monochromatic
- **色彩分级**：Bleach Bypass, Teal and Orange, Day for Night
- **饱和度与对比度**：high saturation, muted tones, low contrast, high contrast
- **色彩情感**：warm and inviting, cold and detached, vibrant, somber

### 3. 灯光技术 (Lighting Techniques)
- **光照设定**：Rembrandt lighting, butterfly lighting, split lighting
- **光线质感**：soft diffused light, harsh direct light, ambient glow
- **光源类型**：golden hour sunlight, blue hour, neon glow, candlelight
- **光影风格**：chiaroscuro, high-key lighting, low-key lighting

### 4. 媒介与质感 (Medium & Texture)
- **创作媒介**：oil on canvas, digital painting, watercolor, charcoal
- **胶片颗粒**：grainy 35mm film, 8mm vintage, cinematic film look
- **表面质感**：matte finish, glossy reflection, textured brush strokes
- **光学效果**：lens flare, chromatic aberration, soft focus, vignette

### 5. 艺术与类型美学 (Art & Genre Aesthetics)
- **艺术流派**：Impressionism, Surrealism, Pop Art, Art Nouveau
- **设计风格**：Art Deco, Brutalism, Minimalism, Cyberpunk
- **艺术家风格**：style of [艺术家名]
- **时代特征**：ukiyo-e, 1980s retro-futurism, Victorian era

## Execution Steps

### Step One: Image Deconstruction
接收用户上传的图片，启动多维度视觉分析。

### Step Two: Visual Pillar Extraction
在五个核心维度中为图片精准打上最关键、最独特的标签。

### Step Three: Forge Universal Style DNA
按照 **[媒介] > [艺术风格] > [光照] > [色彩] > [质感] > [构图]** 优先级，组合成精炼的核心风格字符串。

### Step Four: Generate Application Examples
基于风格DNA生成 2-3 个应用范例，展示如何应用于新主题。

## Output Format

必须严格遵循以下结构：

### 图像概览 (Image Overview)
[一句话概括图片核心内容、主体和基本氛围]

### 视觉元素解构 (Visual Element Deconstruction)
- **电影摄影学分析:** [关键词1], [关键词2], [关键词3]
- **色彩理论分析:** [关键词1], [关键词2], [关键词3]
- **灯光技术分析:** [关键词1], [关键词2], [关键词3]
- **媒介与质感分析:** [关键词1], [关键词2], [关键词3]
- **艺术与类型美学分析:** [关键词1], [关键词2], [关键词3]

### 通用风格DNA (The "Universal Style DNA")
```
[整合所有核心关键词的紧凑风格描述字符串]
```

### 风格应用范例 (Style Application Examples)

**应用范例一：生成新角色**
```
[新角色描述]
[风格DNA]
```

**应用范例二：生成新场景**
```
[新场景描述]
[风格DNA]
```

**应用范例三：生成新物体**
```
[新物体描述]
[风格DNA]
```

## Reference Files

- `cinematography-terms.md` - 电影摄影学术语参考
- `color-theory-guide.md` - 色彩理论速查表
- `lighting-techniques.md` - 灯光技术分类
- `art-movements.md` - 艺术流派风格库

---

## 与本项目 V2.0 规格的映射

**这是「风格锁定 Gate」的核心工具。** 用法：

```
用户上传参考图（或项目已有风格图）
        ↓
style-extractor 提取「通用风格DNA」
        ↓
写入 PROJECT_STATE 的 color_bible / lighting_bible / material_bible / camera_bible
        ↓
登记 LOCK_WORLD / LOCK_COLOR / LOCK_LIGHTING
        ↓
风格DNA 作为「风格英文锚点」全片追加到每条 prompt 末尾
```

| 本文维度 | V2.0 规格对应 |
|---|---|
| 电影摄影学 | §04.6 Camera Bible |
| 色彩理论 | §04.4 Color Bible |
| 灯光技术 | §04.5 Lighting Bible |
| 媒介与质感 | §04.3 Material Bible + §04.1 文明/科技水平 |
| 艺术与类型美学 | `visual_style` 字段 |

> ⚠️ **提取结果必须经用户确认后才锁定**，避免把参考图的偶然特征误当风格基线。
