# 02 化 · 化妆面部 — 源 skill 映射清单

> ⚠️ **本节为初版清单，状态已过时。** 实际抓取进度以 ../INDEX.md（总表）与 ../../源skill库/（已抓归档）为准——多项已抓取完成。


> 职责：肤质、妆容、表情、面部细节、眼神光
> 抓取模板：`https://raw.githubusercontent.com/021gink/short-drama-ai-skills/main/<URL编码路径>`

---

## A. 面部与肤质

| 文件 | 路径 | 用途 | 优先级 |
|---|---|---|---|
| `face-skin-enhancer.md` | `角色/` | 面部肤质增强（核心） | ⭐⭐⭐ |
| `image-character-analyzer.md` | `角色/` | 角色图分析（反推面部特征） | ⭐⭐ |
| `colored-pencil-character-image.md` | `角色/` | 手绘风面部处理 | ⭐ |
| `chibi-transformer.md` | `角色/` | Q版面部简化规则 | ⭐⭐ |

---

## B. 表情与九宫格

| 文件 | 路径 | 用途 | 优先级 |
|---|---|---|---|
| `character-emoji-9grid-i3.md` | `角色/` | 表情九宫格（标准版） | ⭐⭐⭐ |
| `character emoji 9grid i3.md` | `角色/` | 表情九宫格（原始版） | ⭐⭐ |
| `character-emoji-9grid-i3-3.md` | `角色/` | 表情九宫格（变体） | ⭐⭐ |
| `character-special-angle.md` | `角色/` | 特殊角度面部 | ⭐⭐ |

---

## C. 表演与情绪表达（面部延伸）

| 文件 | 路径 | 用途 | 优先级 |
|---|---|---|---|
| `oscar-performance-director.md` | `角色/` | 奥斯卡级表演指导（微表情库） | ⭐⭐⭐ |
| `script-to-dialogue.md` | `音乐/` | 剧本转台词（情绪标注） | ⭐⭐ |

---

## D. 光影配合面部（跨模块）

| 文件 | 路径 | 用途 |
|---|---|---|
| `cinematic-lighting-master.md` | `风格/` | 人像布光（伦勃朗/蝴蝶/环形/分割光）→ 已归档至本地 `03-分镜导演/源skill/` |
| `cinematic-lighting-library.md` | `风格/` | 光影库（15KB） |
| `face-skin-enhancer.md` 配套 | — | 配合 `05-风格光影` 锁定肤质表现 |

---

## 说明：仓库现状与补齐建议

仓库中**没有独立的「妆容设计」skill**（如战损妆、病态妆、古装妆）。当前「化」模块能力来源：

1. `face-skin-enhancer.md` — 肤质基础
2. 表情九宫格系列 — 情绪表达
3. `oscar-performance-director.md` — 微表情
4. `05-风格光影` 的布光公式 — 影响面部呈现

**补齐建议**：在 `00-主控智能体.md` 第三步中已内置「妆面随剧情状态变化」规范（素颜/淡妆/浓妆/战损/病态），可直接由主控 prompt 承担，无需额外源文件。

