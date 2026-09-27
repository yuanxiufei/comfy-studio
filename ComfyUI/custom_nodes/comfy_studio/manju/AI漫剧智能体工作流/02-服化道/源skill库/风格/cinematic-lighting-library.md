---
name: cinematic-lighting-library
display_name: 电影光影库
description: 专业电影光影库，提供经典电影光效、情绪氛围光、场景布光方案及 AI 生成提示词
---

# 电影光影库

## Skill Goal

帮助 AI 视频/图像创作者快速获取专业的电影级光影方案。提供经典电影光效、情绪氛围光、场景布光指南，并一键生成可直接用于 AI 视频/图像生成的英文提示词。

## Workflow

1. 根据用户选择的 `lighting_type` 进入对应分类（classic / mood / scene）
2. 如指定 `style_name`，直接返回匹配的光影方案
3. 如未指定具体风格，根据 `mood` 或 `scene_type` 推荐合适方案
4. 生成英文 AI 提示词和中文说明
5. 返回完整方案：光影名称、中文描述、英文提示词、参考作品、使用建议

## Input Schema

```json
{
  "lighting_type": {
    "type": "string",
    "description": "光影类型分类",
    "enum": ["classic", "mood", "scene"],
    "required": true
  },
  "style_name": {
    "type": "string",
    "description": "具体风格名称，如'教父光'、'赛博朋克'、'忧郁'等",
    "required": false
  },
  "mood": {
    "type": "string",
    "description": "情绪关键词，用于 mood 类型",
    "required": false
  },
  "scene_type": {
    "type": "string",
    "description": "场景类型，用于 scene 类型",
    "required": false
  },
  "output_format": {
    "type": "string",
    "enum": ["prompt", "detailed"],
    "default": "detailed",
    "required": false
  }
}
```

## Output Schema

```json
{
  "name": "光影方案名称",
  "description": "中文详细描述",
  "prompt": "英文AI生成提示词",
  "reference": "参考电影/作品",
  "tips": ["使用建议1", "使用建议2"]
}
```

---

## 光影库内容

### 一、经典电影光效（classic，5 种）

#### 1. 教父光 (The Godfather Lighting)
- **描述**：顶光照明，人物眼睛深陷在阴影中，营造神秘威严的氛围
- **Prompt**：`top lighting, chiaroscuro, dramatic shadows over eyes, low-key lighting, cinematic film noir style, high contrast, moody atmosphere, 1970s cinematic look`
- **参考**：《教父》系列
- **Tips**：使用顶光或高位侧光 / 保持高对比度 / 让人物眼睛部分隐藏在阴影中 / 营造神秘感

#### 2. 赛博朋克光 (Cyberpunk Lighting)
- **描述**：霓虹灯效果，冷暖色彩对比，高饱和度，营造未来都市的夜晚氛围
- **Prompt**：`neon lighting, cyberpunk aesthetic, blue and magenta color contrast, futuristic city lights, glowing neon signs, high saturation, night scene, rain reflections`
- **参考**：《银翼杀手》《攻壳机动队》
- **Tips**：使用霓虹灯作为主要光源 / 强调冷暖对比 / 增加雾气或雨水效果 / 高饱和度色彩

#### 3. 布达佩斯大饭店风格 (Wes Anderson Style)
- **描述**：对称构图，柔和的马卡龙色系，均匀照明，童话般的视觉风格
- **Prompt**：`symmetrical composition, soft pastel colors, even lighting, whimsical atmosphere, vintage aesthetic, warm tones, centered framing, storybook aesthetic`
- **参考**：《布达佩斯大饭店》
- **Tips**：保持画面高度对称 / 使用柔和均匀的光线 / 选择柔和色彩搭配 / 注意构图平衡

#### 4. 银翼杀手光 (Blade Runner Lighting)
- **描述**：雾气中的体积光，光束穿透，未来都市的雨夜氛围
- **Prompt**：`volumetric lighting through fog, god rays, cyberpunk cityscape, rain reflections, neon glow, atmospheric haze, futuristic noir, orange-teal color grading`
- **参考**：《银翼杀手》系列
- **Tips**：使用烟雾或雾气增强光束效果 / 结合霓虹灯和环境光 / 强调体积光 / 营造未来感

#### 5. 诺兰式光 (Nolan Style)
- **描述**：IMAX 电影质感，自然光效，宏大史诗感，注重真实感
- **Prompt**：`IMAX cinematic quality, natural lighting, grand scale, wide shots, realistic lighting, dramatic shadows, film grain, practical lighting`
- **参考**：《盗梦空间》《星际穿越》《敦刻尔克》
- **Tips**：尽可能使用自然光 / 注重真实感 / 大景别展现宏大感 / 保持电影质感

---

### 二、情绪氛围光（mood，5 种）

#### 1. 忧郁氛围光 (Melancholy)
- **描述**：冷色调为主，柔和的阴影，阴天或雨天氛围，传达内心的忧伤
- **Prompt**：`cool color tones, soft shadows, overcast lighting, melancholic atmosphere, blue-gray palette, gentle contrast, rainy mood, muted colors, contemplative feeling`
- **参考**：《海边的曼彻斯特》《断背山》
- **Tips**：使用冷色调 / 降低饱和度 / 柔和的光线过渡 / 营造安静氛围

#### 2. 温暖氛围光 (Warm Lighting)
- **描述**：金色时光，暖色调，柔和光晕，给人温馨舒适的感觉
- **Prompt**：`golden hour lighting, warm color tones, soft glow, sunset atmosphere, orange and amber hues, cozy feeling, golden sunlight, warm embrace`
- **参考**：《请以你的名字呼唤我》《小森林》
- **Tips**：利用日出日落时分 / 强调暖色调 / 使用柔光 / 营造温馨感

#### 3. 神秘氛围光 (Mysterious)
- **描述**：低光环境，深阴影，局部照明，营造悬疑和未知感
- **Prompt**：`low-key lighting, mysterious shadows, selective illumination, dark atmosphere, subtle highlights, enigmatic mood, chiaroscuro, hidden details`
- **参考**：《七宗罪》《消失的爱人》
- **Tips**：保持大部分画面在阴影中 / 使用局部照明 / 强调明暗对比 / 隐藏细节

#### 4. 紧张氛围光 (Tense Lighting)
- **描述**：高对比度，刺眼的光线，不安定的光影变化，传达紧迫感
- **Prompt**：`high contrast lighting, dramatic shadows, tense atmosphere, harsh lighting, suspenseful mood, sharp transitions, thriller style, unsettling shadows`
- **参考**：《电锯惊魂》《黑天鹅》
- **Tips**：增加对比度 / 使用刺眼的光线 / 快速的光影变化 / 营造不安感

#### 5. 浪漫氛围光 (Romantic)
- **描述**：柔光效果，暖色调，梦幻光晕，营造浪漫氛围
- **Prompt**：`soft diffused lighting, romantic atmosphere, warm tones, dreamy bokeh, gentle highlights, intimate mood, candlelight effect, love story aesthetic`
- **参考**：《泰坦尼克号》《爱乐之城》
- **Tips**：使用柔光 / 增加光晕效果 / 暖色调为主 / 营造亲密感

---

### 三、场景布光（scene，4 种）

#### 1. 室内人像布光 (Indoor Portrait)
- **描述**：经典三点布光法，主光、补光、轮廓光组合，专业人像效果
- **Prompt**：`three-point lighting setup, key light, fill light, rim light, studio portrait lighting, professional setup, soft key light, subtle rim light, balanced exposure`
- **Tips**：主光确定基本造型 / 补光填充阴影 / 轮廓光分离背景 / 注意光比控制

#### 2. 城市夜景布光 (City Night)
- **描述**：混合光源，霓虹反射，环境光交织，都市夜晚的独特魅力
- **Prompt**：`mixed city lights, neon reflections, ambient urban lighting, street lamps, building lights, night photography, bokeh lights, urban atmosphere`
- **参考**：《午夜巴黎》《迷失东京》
- **Tips**：利用多种光源 / 注意霓虹灯反射 / 控制高光和阴影 / 营造都市感

#### 3. 自然户外光 (Natural Outdoor)
- **描述**：利用自然光，黄金时段拍摄，展现大自然的美丽光影
- **Prompt**：`golden hour natural light, soft sunlight, warm tones, outdoor photography, natural lighting, sun flare, beautiful sky, nature atmosphere`
- **Tips**：选择合适的时间 / 利用自然反射 / 注意光线方向 / 保护自然色彩

#### 4. 科幻场景布光 (Sci-Fi Scene)
- **描述**：人工光源，冷色调，未来感，营造科幻世界的独特视觉
- **Prompt**：`artificial sci-fi lighting, cool blue tones, futuristic light sources, high-tech environment, synthetic illumination, holographic glow, advanced technology lighting`
- **参考**：《2001 太空漫游》《降临》
- **Tips**：使用冷色调 / 创造未来感光源 / 强调科技感 / 注意光源合理性

---

## Version

- **Version**: 1.0.0
- **Author**: updream 技能工坊
- **Last Updated**: 2025-01

> 原文件含一份将上述库封装为可调用函数的 Python 实现（约 100 行），逻辑为按 `lighting_type` + `style_name` / `mood` / `scene_type` 查表返回。因数据已完整列于上方，实现代码略。

---

## 与本项目 V2.0 规格的映射

| 本文机制 | V2.0 规格对应 |
|---|---|
| 14 种光影方案（classic 5 + mood 5 + scene 4） | §04.5 Lighting Bible 的可选值 |
| 每方案含 Prompt + Tips | §19 PROMPT ENGINE 的 Lighting 字段标准写法 |
| 情绪 → 光影映射 | **与 `02-服化道` 主控第四步的「情绪照明公式表」互补**（规格给了 8 种情绪，本库给了 5 种情绪 + 5 种经典片型） |
| Input/Output Schema | §21 MODEL ADAPTER 的接口化思路（可做成工具调用） |
| 参考作品标注 | §04 世界观建立时的风格参照 |

### 三方互补关系（本项目现有三套光影资料）

| 资料 | 侧重 |
|---|---|
| `引擎/TURNAROUND-STANDARD.md`（本项目自建） | 布光技术本身（伦勃朗/蝴蝶/环形/分割光 + 三点布光） |
| `源skill库/风格/storyboard-lighting-master.md` | **执行流程**（如何与用户确认并批量统一） |
| 本文件 `cinematic-lighting-library.md` | **成品方案库**（直接可用的 14 套光影 + 英文提示词） |

三者组合使用：用本库选方案 → 用 storyboard-lighting-master 的流程执行 → 用 TURNAROUND-STANDARD 校验技术正确性。
