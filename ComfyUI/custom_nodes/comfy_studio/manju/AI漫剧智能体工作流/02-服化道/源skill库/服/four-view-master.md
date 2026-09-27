---
name: four-view-master
display_name: 四视图大师
description: 快速生成角色的三视图参考图，用于角色设计、3D建模、动画制作等工作流程
---

# 四视图大师

> ⚠️ **命名与实际不符**：文件名为「四视图大师」，但正文实现的是**三视图**（正面 + 侧面 + 背面）。归档时保留原名，使用时应按三视图理解。

## Skill Goal

帮助用户快速生成角色的三视图参考图，用于角色设计、3D 建模、动画制作等工作流程。

## Instructions

### 1. 理解用户需求

确认以下信息：
- 角色名称
- 角色描述（外观、服装、配饰等）
- 是否有参考图
- 风格偏好（写实 / 卡通 / 动漫等）

### 2. 生成三视图

**生成参数：**
- `purpose`: `character`
- `aspect_ratio`: `16:9`

**提示词模板：**

```
Character reference sheet, three views, front view + side view + back view,
horizontal layout, {角色描述},
standing pose, full body visible,
clean white background,
professional character design,
highly detailed, consistent style across all views
```

### 3. 使用参考图（如有）

- 将参考图传入 `reference_images` 参数
- 在提示词中强调 `based on reference image, maintain consistent appearance`

### 4. 输出结果

- 展示生成的三视图
- 说明各视图对应的角度
- 询问是否需要调整或生成其他角色

---

## Configuration

```json
{
  "default_resolution": "2K",
  "default_aspect_ratio": "16:9",
  "supported_resolutions": ["2K", "4K"],
  "supported_ratios": ["16:9", "21:9"]
}
```

---

## 与本项目 V2.0 规格的映射

| 本文机制 | V2.0 规格对应 |
|---|---|
| `Character reference sheet, three views, front view + side view + back view` | §06 三视图的**最简英文模板**（可直接复用） |
| `horizontal layout` | §06 的"16:9 横向布局" |
| `clean white background` | §06 纯白背景 |
| `consistent style across all views` | §18 三视图一致性约束 |
| `based on reference image, maintain consistent appearance` | §13 参考图引擎的第一层「身份继承」 |
| 16:9 / 21:9 可选 | 与项目横版 16:9 默认一致 |

### 本项目三视图方案对照（三种模板，按场景选用）

| 模板 | 来源 | 英文骨架 | 适用 |
|---|---|---|---|
| **最简版** | 本文件 | `Character reference sheet, three views, front view + side view + back view, horizontal layout...` | 快速出图 |
| **标准版** | `服/character-turnaround.md` | `character turnaround reference sheet, ..., consistent design, same character, multiple angles...` | 常规使用 |
| **无文字强化版** | `服/character-model-sheet.md` | `character model sheet, multiple views, (front view...:1.3), NO TEXT, ... (any text:1.8)` | 必须零文字时 |

**建议**：默认用标准版；需要严格无文字时用无文字强化版；仅是草稿预览时用最简版。
