# PROMPT TEMPLATES — 提示词引擎与模型适配

> 对应规格 §19 PROMPT ENGINE + §20 双语输出 + §21 MODEL ADAPTER + §38 最终模板

---

## 一、提示词组织顺序（§19，17 项固定序列）

```text
1. Subject              主体
2. Identity             身份
3. Age                  年龄
4. Visual DNA           视觉 DNA
5. Costume              服装
6. Props                道具
7. Pose                 动作
8. Emotion              表情
9. Environment          环境
10. Composition         构图
11. Camera              镜头
12. Lighting            光影
13. Material            材质
14. Style               风格
15. Quality             画质
16. Consistency Constraints  一致性约束
17. Negative Prompt     负面提示
```

> **严格按此顺序组织**，不得颠倒或省略。这是跨模型可移植的基础。

---

## 二、双语输出格式（§20）

**中文输入时：**
```text
中文 Prompt
English Prompt
Negative Prompt
Asset Lock
```

**英文输入时：**
```text
English Prompt
中文 Prompt
Negative Prompt
Asset Lock
```

---

## 三、最终 Prompt 模板（§38）

### 中文模板

```text
主体：
身份：
年龄：
外貌：
视觉锚点：
发型：
服装：
材质：
道具：
动作：
表情：
环境：
构图：
景别：
机位：
镜头：
光影：
色彩：
氛围：
风格：
画质：
一致性约束：
禁止变化：
负面提示：
```

### English Template

```text
Subject:
Identity:
Age:
Appearance:
Visual anchors:
Hair:
Costume:
Materials:
Props:
Pose:
Expression:
Environment:
Composition:
Shot size:
Camera angle:
Lens feeling:
Lighting:
Color:
Atmosphere:
Style:
Quality:
Consistency constraints:
Do not change:
Negative prompt:
```

---

## 四、模型适配层（§21）

> ⚠️ **不要把不同模型的参数混用。不得虚构模型不存在的参数。**

### 4.1 Midjourney / Niji

优先组织：
```text
主体 · 身份 · 视觉锚点 · 服装 · 动作 · 构图 · 光影 · 风格 · 参考 · 比例
```

标准写法：
```
<中文/英文描述>, <视觉锚点>, <服装>, <光影>, <风格> --ar 16:9 --no text, watermark, logo, extra fingers
```

参考图：`--cref <url>`（角色参考）`--sref <url>`（风格参考）`--cw <0-100>`（参考权重）

### 4.2 Stable Diffusion / FLUX

```text
Positive Prompt:  <17 项序列的 1~15 项>
Negative Prompt:  <见 NEGATIVE-PROMPT-LIBRARY>
Character Reference:  <角色参考图>
Style Reference:      <风格参考图>
Pose Guidance:        <姿势引导>
Composition:          <构图>
Lighting:             <光影>
Quality:              <画质>
```

按用户指定工作流再使用（**不要默认强加**）：
LoRA · ControlNet · IP-Adapter · reference image · inpainting · outpainting

### 4.3 GPT Image / 通用图像模型

使用**自然语言视觉 Brief**：
```text
主体
构图
空间
角色一致性
参考图约束
材质
灯光
背景
比例
禁止变化项
```

### 4.4 Seedance / 可灵 / Vidu（视频）

中文自然语言段落：
```
[镜头语言/运动方式] + [主体详细外貌与动作过程] + [环境与背景细节] + [光影、色彩与氛围] + [画质与物理引擎参数]
```
禁止英文 tag 堆砌。

---

## 五、模块专用输出协议（§34~§37）

### 默认角色输出协议（§34）

用户说「生成这个角色」时，严格按序执行：
```
STEP 1  建立 Character DNA
STEP 2  自动补齐必要视觉变量
STEP 3  生成图像          ← 图像优先！
STEP 4  输出中文 Prompt
STEP 5  输出 English Prompt
STEP 6  输出 Negative Prompt
STEP 7  输出 Asset Lock
```
> ⚠️ **不得把大量解释放在图像生成之前。**

### 默认服装输出协议（§35）

```
图像 → 中文 Costume Prompt → English Costume Prompt → Negative Prompt → Material Lock → Color Lock
```

### 默认道具输出协议（§36）

```
图像 → 中文 Prop Prompt → English Prop Prompt → Negative Prompt → Prop ID → Scale Lock
```

### 默认环境输出协议（§37）

```
图像 → 中文 Environment Prompt → English Environment Prompt → Negative Prompt → Environment Lock → Lighting Lock
```

---

## 五·补｜快速公式（三段式）

> 来源：`源skill库/管线/script-to-art-assets.md`
> 用途：17 项完整序列较重，**草稿/快出/沟通**时可用三段式；定稿仍走 17 项。

### 角色设计

```
[角色名称/身份] + [核心外貌特征] + [标志性服饰] + [材质细节描述] + [光影与构图标签]
```

### 场景设计

```
[场景名称] + [空间布局/建筑风格] + [环境氛围词] + [特定光效(如丁达尔/月光)] + [镜头景别建议]
```

### 道具设计

```
[道具主体] + [构造与材质] + [工业/艺术风格说明] + [背景环境说明]
```

**技术规范（三段式同样适用）：**
- 中英双语输出（中文用于国产模型，英文用于 MJ 等）
- 自动注入画质标签：`high resolution`, `extremely detailed`, `8K`, `cinematic lighting`
- **核心风格词（Style Keyword）在同一剧本内保持高度统一**（即风格锚点）

**示例：**

> 剧本：「陈平推开尘封已久的地下密室，看到中央桌子上摆放着一个闪烁着幽蓝光芒的古老罗盘。」

- 场景：`Underground secret room, damp stone walls, moss-covered, dim moonlight leaking through cracks, dusty air, volumetric lighting, cinematic atmosphere.`
- 道具：`Ancient compass, bronze material, intricate cloud pattern carvings, glowing blue gemstone at the center, mystical energy, close-up shot, high precision.`

---

## 五·补2｜光影字段六维公式（Lighting 字段标准写法）

> 来源：`源skill库/风格/storyboard-lighting-master.md`
> 用途：**本项目所有出图的 Lighting 字段一律按此六步组合**，保证全片光影可复现。

```
① 基础风格词  从「风格库」选 1 个（伦勃朗光/蓝调夜景/丁达尔光/黑色电影/黄金时刻…共 23 种）
② 光源类型词  选 1～2 个（moonlight / neon light / street light / candlelight …）
③ 方向/光质词 选 1 个（side lighting / backlighting / soft lighting / dramatic lighting …）
④ 氛围情绪词  选 1 个（moody / mysterious / romantic / cinematic / low-key …）
⑤ 特殊光效词  选 0～1 个（bloom effect / lens flare / god rays / caustics …）
⑥ 固定附加词  subtle backlight, 微微逆光   ← 每次必加，不可省略
```

**组合示例（蓝调夜景）：**
```
blue hour, cool moonlight, subtle ambient blue, night atmosphere,
moonlight, street light,
side lighting, soft lighting,
moody lighting, mysterious lighting,
bloom effect,
subtle backlight, 微微逆光
```

**光影重绘（只改光影、其余全锁）时的固定句式：**
```
将图片的光影改成 [按六维公式组合好的提示词]，
保持原有人物构图与服装不变，仅调整光照方向、色调和阴影，
subtle backlight, 微微逆光, photorealistic lighting, high quality render, 8K
```
负面词：`flat lighting, overexposed, underexposed, harsh shadows, dirty shadows, blown highlights, unnatural skin tone, color cast`

**批量铁则**：批量重绘时，所有图片必须用与测试图**完全相同的提示词，一字不差**（LOCK_LIGHTING 的落地纪律）。

---

## 五·补3｜风格锁定的三种手段（择一，不得混用）

| 手段 | 来源 | 适用 | 写法 |
|---|---|---|---|
| **A 风格 DNA** | `源skill库/风格/style-extractor.md` | **有参考图时优先** | 五维解构 → 按 `[媒介]>[艺术风格]>[光照]>[色彩]>[质感]>[构图]` 组合成 DNA 字符串 |
| **B LUT 预设** | `源skill库/风格/hollywood-lut.md` | 无参考图时最省事 | 固定追加同一 LUT 词（如 `teal and orange color grading`） |
| **C 光影六维** | 本文件上一节 | 需要精细控制光影时 | 六步组合（可与 A/B 叠加，但 A 与 B 互斥） |

⚠️ **A 与 B 不得混用**：DNA 是从实际图片提取的，LUT 是通用预设，两者叠加会导致色彩冲突。

---

## 六、高质量化指令的具体化要求（§49）

用户说「高级感 / 电影感」时，**不要只加** `cinematic, beautiful, masterpiece`。

必须具体化为：
```text
controlled key light          受控主光
soft fill                     柔和辅光
subtle rim light              微妙轮廓光
physically plausible falloff  物理合理的衰减
controlled contrast           受控对比度
cinematic depth               电影级景深
foreground / midground / background separation   前中后景分离
restrained color palette      克制的色彩
material separation           材质区分
```

---

## 七、写实化指令（§48）

用户说「写实」时提高：
```text
skin realism                  皮肤真实感
physically plausible materials 物理合理材质
realistic lighting            真实光照
realistic proportions         真实比例
micro texture                 微观纹理
subsurface appearance         次表面散射
material response             材质响应
```
> 但仍**保持原始 Character DNA**，不得改变五官身份。
