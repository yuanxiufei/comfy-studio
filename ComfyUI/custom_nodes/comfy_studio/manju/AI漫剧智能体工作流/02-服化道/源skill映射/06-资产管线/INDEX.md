# 06 资产管线 — 源 skill 映射清单

> ⚠️ **本节为初版清单，状态已过时。** 实际抓取进度以 ../INDEX.md（总表）与 ../../源skill库/（已抓归档）为准——多项已抓取完成。


> 源目录：`工具/`（21 文件）+ `SD2审核筛查/`（7 文件）
> 职责：资产入库、质检、命名规范、模型分流、生成监督
> 抓取模板：`https://raw.githubusercontent.com/021gink/short-drama-ai-skills/main/%E5%B7%A5%E5%85%B7/<文件名>`

---

## A. 资产管理（核心）

| 文件 | 用途 | 优先级 |
|---|---|---|
| `character-asset-supervisor.md` | 资产监工（质检总控，2.2KB） | ⭐⭐⭐ |
| `character-asset-uploader.md` | 资产入库上传 | ⭐⭐⭐ |
| `asset-expander.md`（在 `角色/`） | 资产扩展（衍生变体） | ⭐⭐ |
| `canvas-organizer.md` | 画布组织（13KB，资产排布） | ⭐⭐⭐ |
| `extract-last-frame.md` | 提取尾帧（视频→图片资产） | ⭐⭐ |

---

## B. 生成监督与分流

| 文件 | 用途 | 优先级 |
|---|---|---|
| `视频生成监督器.md` | 视频生成监督（4.6KB） | ⭐⭐⭐ |
| `智能模型分流器.md` | 模型分流（按任务选模型） | ⭐⭐ |
| `user-feedback.md` | 用户反馈收集（11KB） | ⭐⭐ |
| `super-saver-assistant-i2.md` | 成本节省助手 | ⭐ |

---

## C. 提示词工程（跨模块复用）

| 文件 | 用途 | 优先级 |
|---|---|---|
| `GPT-Image-2 提示词工程师.md` | GPT-Image-2 提示词工程（18KB） | ⭐⭐⭐ |
| `aigc-prompt-optimizer-v2.md` | AIGC 提示词优化（19KB） | ⭐⭐⭐ |
| `prompt-architect.md` | 提示词架构师（12KB） | ⭐⭐ |
| `gpt-image-prompt-engineer.md` | GPT-Image 提示词工程 | ⭐⭐ |
| `Gimage2 提示词优化器.md` / `gimage2-prompt-optimizer.md` / `gimage2-prompt-optimizer-3.md` / `gimage2 prompt optimizer.md` | Gimage2 优化器（四版本） | ⭐⭐ |
| `Seedance-image-2提示词.md` | Seedance-Image 提示词 | ⭐⭐ |
| `prompt-engineer-4l9d.md` | 提示词工程变体 | ⭐ |
| `bootstrap-video.md` | 视频引导（29KB） | ⭐⭐ |

---

## D. 其他工具

| 文件 | 用途 |
|---|---|
| `art-ai-start.md` | 美术 AI 起步 |
| `updream高阶使用指南.md` | Updream 平台指南（15KB） |
| `推斯特zz.md` | 工作流工具 |

---

## E. 合规审核（SD2 系列）

| 文件 | 路径 | 用途 | 优先级 |
|---|---|---|---|
| `sd2-video-prompt-expert.md` | `SD2审核筛查/` | SD2 视频提示词专家 | ⭐⭐ |
| `seedance-prompt-filter.md` | `SD2审核筛查/` | Seedance 提示词过滤 | ⭐⭐⭐ |
| `seedance-prompt-optimizer-i2.md` | `SD2审核筛查/` | 过审优化器 | ⭐⭐⭐ |
| `seedance-compliance-director.md` | `SD2审核筛查/` | 合规导演 | ⭐⭐ |
| `seedancepromptoptimizer.md` | `SD2审核筛查/` | 优化器完整版（27KB） | ⭐⭐⭐ |
| `seedance-prompt-template.md` | `SD2审核筛查/` | 提示词模板（13KB） | ⭐⭐ |
| `lingjian-prompt-inspector.md` | `SD2审核筛查/` | 提示词检查器（27KB） | ⭐⭐ |
| `SD视频提示词过审核优化器.md` | `SD2审核筛查/` | 过审优化中文版 | ⭐⭐ |

> 合规部分也可独立成 `06-合规审核/` 模块（工作流根目录已预留）。

---

## 工作流定位（资产质检 Gate）

```
【6.1】资产产出（来自 01 服 / 02 化 / 03 道 / 04 景）
        ↓
【6.2】质检     ← character-asset-supervisor
        检查项：分辨率 / 透明通道 / 比例一致 / 色值偏移 / 风格锚点追加
        ↓
【6.3】命名规范 → 项目_模块_角色/场景_名称_版本.扩展名
        ↓
【6.4】入库     ← character-asset-uploader + canvas-organizer
        ↓
【6.5】资产清单输出（含提示词与参考图路径）
        ↓
【6.6】过审检查 ← seedance-prompt-filter（如用于视频生成）
        ↓
*** 资产质检 Gate 通过后交接 03-分镜导演 / 04-视频生成 ***
```

## 建议抓取顺序

1. `character-asset-supervisor.md`（质检总控）
2. `canvas-organizer.md`（资产排布）
3. `GPT-Image-2 提示词工程师.md`（提示词工程）
4. `seedance-prompt-filter.md`（过审）
5. `视频生成监督器.md`（生成监督）
6. `character-asset-uploader.md`（入库）

