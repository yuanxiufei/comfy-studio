---
name: vr-panorama-generator
display_name: VR 全景图生成器
enable: true
description: 自动生成标准化的 360° VR 全景图提示词，支持中英文双语输出，提供推荐生成参数，可融合参考图生成高质量 VR 适配图像
trigger: 当用户想要生成 360° VR 全景图、等距柱状投影图、或 VR 适配的图片时
---

> **本文解决的问题**：V2.0 规格 §09 场景引擎要求"多角度空间逻辑"，本文件提供了**最彻底的空间覆盖方案**——360° 全景，可直接作为场景空间关系的终极参考。

# VR 全景图生成器

## Skill Goal

快速生成专业级的 360° VR 全景图提示词，确保输出符合等距柱状投影标准，适配 VR 设备观看。

---

## Step One：分析用户需求

1. 提取用户描述的场景/主题内容
2. 检查是否提供了参考图
3. 确认用户需要的风格（写实、科幻、自然、建筑等）

---

## Step Two：组装 VR 全景图提示词

**中文正向提示词模板：**
```
360°等距柱状投影, 2:1宽高比例, 无缝拼接, 边缘无畸变, VR适配, 8K超高清,
高动态范围HDR, 无噪点, 细节拉满, [用户场景描述]
```

**英文正向提示词模板：**
```
360° equirectangular projection, 2:1 aspect ratio, seamless stitching,
edge distortion free, VR compatible, 8K UHD, HDR, noiseless, rich details,
[user scene description]
```

**反向提示词（固定，中英双写）：**
```
透视畸变, 画面残缺, 纹理重复, 拼接缝隙, 低分辨率伪影, 非等距投影畸变,
人工合成痕迹, 色彩断层, 噪点, 水印,
perspective distortion, broken frame, texture repeating, stitching seams,
low resolution artifacts, non-equirectangular distortion, artificial traces,
color banding, noise, watermark, fish eye lens distortion, stitching artifact
```

---

## Step Three：输出完整配置

1. 中文正向提示词
2. 英文正向提示词
3. 反向提示词
4. 推荐生成参数

**推荐生成参数：**

| 项 | 值 |
|---|---|
| 分辨率 | `5824×2880`（2:1 比例） |
| 采样器 | DPM++ 2M Karras |
| 步数 | 28–35 |
| CFG Scale | 7–9 |

---

## Step Four：使用建议

- 建议使用支持等距柱状投影的模型
- 推荐用于 VR 头显观看的场景
- 提示可用于图生图时保持 VR 格式

---

## Example

**用户输入：** 「帮我生成一个森林场景的 VR 全景图提示词」

**输出：**

```
## 中文正向提示词
360°等距柱状投影, 2:1宽高比例, 无缝拼接, 边缘无畸变, VR适配, 8K超高清,
高动态范围HDR, 无噪点, 细节拉满, 茂密原始森林, 阳光穿透树冠, 苔藓覆盖的地面,
晨雾弥漫, 宁静祥和的自然氛围

## 英文正向提示词
360° equirectangular projection, 2:1 aspect ratio, seamless stitching,
edge distortion free, VR compatible, 8K UHD, HDR, noiseless, rich details,
dense primeval forest, sunlight filtering through canopy, moss-covered ground,
morning mist, peaceful and serene natural atmosphere
```

---

## Technical Notes

- **等距柱状投影 (Equirectangular Projection)** 是 VR 全景图的标准格式
- **2:1 宽高比**确保 360° 水平 × 180° 垂直视野完整覆盖
- 高分辨率 (8K) 确保 VR 设备观看时细节清晰
- HDR 增强动态范围，提升沉浸感

---

## 与本项目 V2.0 规格的映射

| 本文机制 | V2.0 规格对应 |
|---|---|
| **360° 全景** | **§32 场景空间关系的最彻底方案**——一张图覆盖全部方位，比 S01–S06 六角度更完整 |
| 「等距柱状投影」标准 | 可作为场景资产的**空间基准图** |
| 固定反向提示词（防拼接缝隙/畸变） | §22 NEGATIVE PROMPT ENGINE 的场景专项 |
| 推荐生成参数（分辨率/采样器/步数/CFG） | **§21 MODEL ADAPTER 的具体参数示例**（规格说"不得虚构参数"，本文件给了真实可用的 SD 参数） |
| HDR / 8K | §51 质量参数 |

### 与 `scene-multi-angle-generator` 的分工

| 方案 | 输出 | 用途 |
|---|---|---|
| **多角度生成器**（S01–S06） | 6 张分角度图 + 索引表 | 分镜选图查表（**主力方案**） |
| **VR 全景**（本文件） | 1 张 360° 等距柱状图 | **空间基准**——可作为场景圣经的可视化底板，或 VR 展陈 |

**建议组合**：先用 VR 全景确定**空间的完整布局**（避免只顾一面墙），再用多角度生成器产出分镜可用角度。两者结合可显著降低空间逻辑错误。
