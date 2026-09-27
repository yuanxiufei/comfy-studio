# TURNAROUND STANDARD — 出图硬标准

> **相关文件**：`../01-资产库出图引擎.md` 是本标准的**可部署执行版**（含 11 维度自动补全、4 套世界观材质库、固定 16:9 版式与完整 Prompt 模板）。
> 本文件是**规则查询层**（四类资产硬标准 + 21:9 与三种模板变体）；需要"拿一句话直接出图"时用出图引擎。

> 对应规格 §06 CHARACTER TURNAROUND + §07 COSTUME + §08 PROP + §09 ENVIRONMENT + §51 最终系统指令
> **本文是可直接拼接进 prompt 的标准段落。**

---

## 一、角色三视图标准（§06）

### 1.1 默认硬标准

| 项 | 标准 |
|---|---|
| 画幅 | 16:9 |
| 背景 | 纯白背景 |
| 左侧布局 | 放大头部 / 面部细节 |
| 右侧布局 | 正面全身 → 侧面全身 → 背面全身 |
| 灯光 | 柔和均匀灯光 |
| 阴影 | 无明显阴影 |
| 灯光质量 | 电影级灯光质量 |
| 风格 | 写实 / 拟真人 / 半写实优先 |
| 细节 | 超高细节 |
| 分辨率 | 8K 级视觉细节 |
| 禁止项 | 无文字 · 无字母 · 无 Logo · 无水印 · 无字幕 · 无随机符号 |

### 1.2 原始三视图生产标准（§06 硬标准）

```
人物主体来自用户输入
柔和均匀打光
无明显阴影
拟真人
干净通透
超真实
16:9
左侧放大正面头部细节
右侧人物三视图
纯白背景
8K 高清细节
```

### 1.3 可拼接英文标准段

```
Character turnaround sheet, 16:9, pure white background, seamless white studio background,
left side: enlarged head and facial detail close-up, right side: front view full body,
side view full body, back view full body, soft even lighting, no harsh shadows,
cinematic lighting quality, photorealistic, hyper detailed, 8k visual detail,
no text, no letters, no logo, no watermark, no caption, no random symbols
```

### 1.4 三视图负面词（必加）

```
inconsistent character design, different face between views, different hairstyle,
different costume, different age, different skin tone, different eye color,
inconsistent accessories, inconsistent body proportions, cropped head, cropped feet,
overlapping views, merged limbs, duplicate character, extra character
```

### 1.5 三种三视图模板（按场景选用）

| 模板 | 英文骨架 | 适用 | 来源 |
|---|---|---|---|
| **最简版** | `Character reference sheet, three views, front view + side view + back view, horizontal layout, ...` | 快速出草稿 | `源skill库/服/four-view-master.md` |
| **标准版** | `character turnaround reference sheet, ..., consistent design, same character, multiple angles, ...` | **常规默认** | `源skill库/服/character-turnaround.md` |
| **无文字强化版** | `character model sheet, multiple views, (front view, side profile view, back view:1.3), NO TEXT, ...` | **必须零文字时** | `源skill库/服/character-model-sheet.md` |

**默认用标准版；需要严格零文字时用无文字强化版；仅草稿预览时用最简版。**

### 1.6 文字屏蔽的强制写法（RULE-005 落实）

⚠️ 单纯写 `no text` **不够**，必须使用**带权重的反向提示词**：

```
正向追加：NO TEXT, no annotations, no labels, no words
反向追加：(text, font, letters, words, annotations, labels, descriptions,
          dimensions, handwriting, chart, arrows, indicators, view labels,
          any text:1.8), signature, watermark, username, logo, speech bubble
```

**关键词**：`(any text:1.8)` —— **权重 1.8** 是关键，缺了它模型仍会生成标注文字。

**输图后必须逐字检查隐蔽位置**：背景招牌、书页、屏幕、衣物印字、包装、道具铭文。

### 1.7 另一种布局：21:9 左主右辅（信息量优先）

| 布局 | 比例 | 左侧 | 右侧 | 适用 | 来源 |
|---|---|---|---|---|---|
| **规格 §06 标准** | 16:9 | 头部/面部特写 | 正/侧/背三视图 | **角色定妆（默认）** | 规格 §06 |
| **信息量优先** | 21:9 或 2:1 | 三视图（约 65%） | 配饰细节 + 服装纹理 + 表情特写（约 35%） | 一次性给全信息 | `源skill库/服/character-model-sheet.md` |

**21:9 布局追加提示词：**
```
, accessory details on right side, weapon close-up, jewelry details,
costume texture details, prop showcase, facial expression variations on right side,
(happy face, angry face, sad face, excited face:1.2), arranged on right edge, consistent character
```

---

## 二、服装标准（§07）

服装**必须独立成资产**，不得依附人物图。

### 2.1 必填描述字段（25 项）

```
时代 · 身份 · 阶层 · 用途 · 版型 · 剪裁 · 领型 · 袖型 · 肩部 · 腰部 ·
下摆 · 扣件 · 缝线 · 刺绣 · 纹样 · 层次 · 面料 · 厚度 · 垂坠 · 磨损 ·
使用痕迹 · 主色 · 辅色 · 配件 · 穿戴逻辑
```

### 2.2 默认构图

| 项 | 标准 |
|---|---|
| 画幅 | 16:9 |
| 背景 | 纯白背景 |
| 左侧 | 面料 / 结构细节 |
| 右侧 | 正面 → 侧面 → 背面 |
| 灯光 | 柔和均匀光 · 电影级灯光 |
| 细节 | 高细节 |
| 禁止项 | 无文字 · 无 Logo · 无水印 |

### 2.3 可拼接英文标准段

```
Costume design sheet, 16:9, pure white background, seamless white studio background,
left side: fabric and construction detail close-up, right side: front view, side view, back view,
flat garment presentation, soft even lighting, cinematic lighting quality, high detail,
material accurate, no text, no logo, no watermark
```

### 2.4 服装负面词

```
confused garment structure, wrong wearing order, ambiguous material, merged layers,
missing accessories, misaligned patterns
结构混乱, 穿戴顺序错误, 材质不明, 层次融合, 配饰缺失, 图案错位
```

---

## 三、道具标准（§08）

道具**必须独立生成**。

### 3.1 必填描述字段（19 项）

```
名称 · 用途 · 时代 · 使用者 · 尺寸 · 比例 · 结构 · 材料 · 工艺 · 表面 ·
纹理 · 磨损 · 功能 · 机关 · 握持 · 收纳 · 重量感 · 与人物比例
```

### 3.2 默认构图

| 项 | 标准 |
|---|---|
| 背景 | 纯白背景 |
| 画幅 | 16:9 |
| 左侧 | 结构 / 材质特写 |
| 右侧 | 多角度视图：正面 → 侧面 → 背面 |
| 灯光 | 柔和均匀灯光 · 电影级灯光 |
| 细节 | 高细节 |
| 禁止项 | 无文字 / Logo / 水印 |

### 3.3 可拼接英文标准段

```
Prop design sheet, 16:9, pure white background, seamless white studio background,
left side: structure and material detail close-up, right side: multi-angle views —
front, side, back, product photography lighting, soft even lighting, cinematic lighting quality,
high detail, material accurate, no text, no logo, no watermark
```

### 3.4 道具负面词

```
inconsistent angles, distorted scale, wrong structure, confused materials, extra parts
角度不一致, 比例失真, 结构错误, 材质混淆, 多出部件
```

---

## 四、场景标准（§09）

> ⚠️ **环境不使用纯白背景。** 这是与前三类资产的核心区别。

### 4.1 必须生成要素

```
建筑 · 空间 · 材料 · 光线 · 氛围 · 时代 · 尺度 · 人物动线 · 前景 · 中景 · 后景
```

### 4.2 一致性要求（§09）

环境必须与 `Character + Costume + Props` 保持一致：

- 建筑年代与世界观相符
- 材料质感与 Material Bible 相符
- 光源方向与 Lighting Bible 相符
- 空间尺度与角色身高比例相符
- 陈设中的道具与 PROP INDEX 对应

### 4.3 多角度空间逻辑（§32）

同一 ENV 的多角度必须锁定：建筑 · 门窗 · 家具 · 地面 · 光源 · 主空间关系
允许变化：天气 · 时间 · 人物 · 灯光状态 · 道具摆放

### 4.4 可拼接英文标准段

```
Cinematic environment, [建筑类型], [空间尺度], [材料], [光线方向与性质],
[氛围], foreground / midground / background separation, atmospheric depth,
consistent architecture, physically plausible materials, cinematic lighting quality,
high detail, no text, no logo, no watermark
```

### 4.5 场景负面词

```
pure white background, contradictory spatial logic, abrupt architecture change,
contradictory light sources, wrong scale
纯白背景, 空间逻辑矛盾, 建筑结构突变, 光源矛盾, 尺度错误
```

### 4.6 场景空间基准方案：360° 全景（来源：`源skill库/景/vr-panorama-generator.md`）

> **用途**：先出一张 360° 全景确定**空间的完整布局**，避免"只顾一面墙"导致后续多角度空间矛盾。
> 与 S01–S06 的关系：**全景定基准 → 六角度出分镜可用图**。

**中文正向模板：**
```
360°等距柱状投影, 2:1宽高比例, 无缝拼接, 边缘无畸变, VR适配, 8K超高清,
高动态范围HDR, 无噪点, 细节拉满, [场景描述]
```

**英文正向模板：**
```
360° equirectangular projection, 2:1 aspect ratio, seamless stitching,
edge distortion free, VR compatible, 8K UHD, HDR, noiseless, rich details,
[scene description]
```

**反向提示词（固定，中英双写）：**
```
透视畸变, 画面残缺, 纹理重复, 拼接缝隙, 低分辨率伪影, 非等距投影畸变,
人工合成痕迹, 色彩断层, 噪点, 水印,
perspective distortion, broken frame, texture repeating, stitching seams,
low resolution artifacts, non-equirectangular distortion, artificial traces,
color banding, noise, watermark, fish eye lens distortion, stitching artifact
```

**推荐生成参数（真实可用，非虚构）：**

| 项 | 值 |
|---|---|
| 分辨率 | `5824×2880`（2:1） |
| 采样器 | `DPM++ 2M Karras` |
| 步数 | 28–35 |
| CFG Scale | 7–9 |

**技术要点：**
- 等距柱状投影（Equirectangular Projection）是 VR 全景标准格式
- 2:1 宽高比确保 360° 水平 × 180° 垂直完整覆盖
- 8K 分辨率保证 VR 设备观看时细节清晰
- HDR 增强动态范围

**本项目用法建议：**
1. 场景首次建立时，先出 360° 全景 → 作为**场景圣经的可视化底板**
2. 再按 `INDEX-TEMPLATES.md` §4.1 生成 S01–S06 六角度，全部以全景为空间参照
3. 分镜阶段按景别/方位查 S01–S06 索引表取参考图

---

## 五、四类资产速查对照

| 项 | 角色 | 服装 | 道具 | 场景 |
|---|---|---|---|---|
| 背景 | 纯白 | 纯白 | 纯白 | **非白（实景）** |
| 画幅 | 16:9 | 16:9 | 16:9 | 按镜头需要 |
| 左侧 | 头部细节 | 面料细节 | 结构特写 | — |
| 右侧 | 三视图 | 正/侧/背 | 多角度 | 多角度空间 |
| 灯光 | 柔和均匀 | 柔和均匀 | 柔和均匀 | 电影级氛围光 |
| 文字 | 禁止 | 禁止 | 禁止 | 禁止 |
| 独立资产 | ✅ | ✅ | ✅ | ✅ |
| 对应索引 | CHARACTER INDEX | COSTUME INDEX | PROP INDEX | ENVIRONMENT INDEX |

---

## 六、质量参数默认值（§51）

```
写实 / 拟真人优先
超高细节
8K 级视觉细节
电影级灯光质量
```

**电影感必须具体化（§49），不得只写 `cinematic, masterpiece`：**
```
controlled key light, soft fill, subtle rim light, physically plausible falloff,
controlled contrast, cinematic depth, foreground / midground / background separation,
restrained color palette, material separation
```

---

## 七、光影设计的三个来源与分工（避免重复查阅）

本项目的光影资料分散在三处，**各司其职，不重复**：

| 层 | 位置 | 内容 | 何时用 |
|---|---|---|---|
| **技术层** | 本文件 §六 + `PROMPT-TEMPLATES.md` §五·补2 | 布光技术本身（伦勃朗/蝴蝶/环形/分割光 + 三点布光）、光影六维公式 | 需要知道**怎么布光** |
| **流程层** | `源skill库/风格/storyboard-lighting-master.md` | 与用户确认光影并**批量统一全片**的交互流程 + 23 种风格库 | 需要**统一全片光影** |
| **方案库层** | `源skill库/风格/cinematic-lighting-library.md` | 14 套成品方案（classic 5 / mood 5 / scene 4），每套含英文 Prompt + 参考作品 | 需要**现成方案** |
| **色调层** | `源skill库/风格/hollywood-lut.md` | 6 种 LUT 预设（青橙/黄金时刻/黑色电影/黑金/赛博霓虹/去饱和战场） | **无参考图时最省事的统一手段** |

**已提炼进本项目引擎的部分（日常直接用这些）：**

| 已提炼内容 | 落点 |
|---|---|
| 光影六维公式（①基础风格+②光源+③方向光质+④氛围+⑤特殊光效+⑥固定附加词） | `PROMPT-TEMPLATES.md` §五·补2 |
| 光影重绘固定句式（只改光影、其余全锁） | `PROMPT-TEMPLATES.md` §五·补2 |
| 风格预设记录卡字段 | `模板/PROJECT_STATE.yaml` → `lighting_preset` |
| 风格锁定三手段（DNA / LUT / 六维，A 与 B 互斥） | `PROMPT-TEMPLATES.md` §五·补3 + `模板/VISUAL_BIBLE.md` §4.8 |

**交叉使用顺序建议：**
```
选方案（方案库/LUT）
   ↓
按六维公式写成提示词（PROMPT-TEMPLATES）
   ↓
与用户确认 → 写入 PROJECT_STATE.lighting_preset
   ↓
批量出图/重绘时逐字复用该提示词（批量铁则）
   ↓
出图后跑风格匹配度评分（CONSISTENCY-CHECKLIST §二·补）
```
