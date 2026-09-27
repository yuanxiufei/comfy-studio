# 01 · 剧本文本 · 源文件映射清单

> 职责：剧本创作、小说改编、结构诊断、钩子设计
> 状态：✅ **模块已可用**（`00-主控智能体.md` + `模板/`）。本文件为**能力扩充素材清单**，列出仓库 `文档/` 目录 33 个可抓取的源 skill。
> 对应用户原 GPT：AI剧本智能体
> 完整能力说明见 `./README.md`

---

## 待抓取（仓库 `文档/` 目录，33 文件）

### A. 剧本创作（核心）

| 文件 | 用途 | 优先级 |
|---|---|---|
| `YubAI-DramaFlow.md` | 短剧全流程（32KB，最全） | ⭐⭐⭐ |
| `screenplay-series.md` | 剧集剧本创作（24KB） | ⭐⭐⭐ |
| `screenplay-ultrashort.md` | 超短剧剧本（14KB） | ⭐⭐⭐ |
| `screenplay-short.md` | 短片剧本（8.5KB） | ⭐⭐⭐ |
| `bootstrap-script.md` | 剧本引导（6.7KB） | ⭐⭐ |
| `one-sentence-script.md` | 一句话剧本 | ⭐⭐ |
| `CP小剧场剧本生成器.md` | CP 小剧场 | ⭐⭐ |
| `comedy_script_writer.md` | 喜剧编剧 | ⭐⭐ |
| `班迪编剧系统.md` | 编剧系统 | ⭐⭐ |
| `羽洛短剧私塾轻量版V1.md` | 短剧教学 | ⭐ |

### B. 小说改编

| 文件 | 用途 | 优先级 |
|---|---|---|
| `xiaoshuo 小说创作全流程助手.md` | 小说创作全流程（30KB） | ⭐⭐⭐ |
| `auto_novel_writer.md` | 自动小说写作（30KB） | ⭐⭐⭐ |
| `novel-to-script-pro（剧本）.md` | 小说转剧本 | ⭐⭐⭐ |
| `novel-to-short-drama.md` | 小说转短剧 | ⭐⭐⭐ |
| `anime-lightnovel-parser-i2.md` | 轻小说解析 | ⭐⭐ |
| `Story Expander.md` | 故事扩展 | ⭐⭐ |
| `brainstorm-to-blockbuster.md` | 头脑风暴到大片 | ⭐⭐ |

### C. 结构与诊断

| 文件 | 用途 | 优先级 |
|---|---|---|
| `script-doctor.md` | 剧本医生（诊断） | ⭐⭐⭐ |
| `short-drama-hook-generator.md` | 短剧钩子生成器（5KB） | ⭐⭐⭐ |
| `chapter-continuity-advisor.md` | 章节连贯性顾问 | ⭐⭐ |
| `character-extractor.md` | 角色提取（→ 交接 02 服化道） | ⭐⭐⭐ |
| `Bootstrap Outline.md` | 大纲引导 | ⭐⭐ |
| `gaiman-storytelling.md` | 盖曼叙事法（9.3KB） | ⭐⭐ |
| `fact-checker.md` | 事实核查 | ⭐ |
| `ip-guardian-director.md` | IP 守护导演 | ⭐⭐ |

### D. 漫剧专项

| 文件 | 用途 | 优先级 |
|---|---|---|
| `全自动流AI漫剧生成器-longzeflow.md` | 全自动漫剧流 | ⭐⭐⭐ |
| `漫剧导演工坊.md` | 漫剧导演工坊 | ⭐⭐⭐ |
| `一句话漫剧.md` | 一句话漫剧 | ⭐⭐ |
| `nnnec-exp-002.md` | 实验性流程 | ⭐ |

---

## 工作流定位（整条生产线的起点）

```
【5.1】创意 → 大纲      ← Bootstrap Outline / brainstorm-to-blockbuster
        ↓
【5.2】大纲 → 剧本      ← screenplay-series / YubAI-DramaFlow
        ↓
【5.3】小说 → 剧本      ← novel-to-script-pro（如为改编）
        ↓
【5.4】钩子强化         ← short-drama-hook-generator
        ↓
【5.5】剧本诊断         ← script-doctor
        ↓
【5.6】角色提取         ← character-extractor
        ↓
→ 交接给【02 服化道】（角色小传）与【03 分镜导演】（分集剧本）
```

## 抓取模板

```
https://raw.githubusercontent.com/021gink/short-drama-ai-skills/main/%E6%96%87%E6%A1%A3/<文件名>
```

## 建议抓取顺序

1. `YubAI-DramaFlow.md`（全流程总纲）
2. `short-drama-hook-generator.md`（钩子，短剧命门）
3. `character-extractor.md`（角色提取，衔接服化道）
4. `screenplay-ultrashort.md`（超短剧剧本）
5. `script-doctor.md`（诊断）
6. `novel-to-script-pro（剧本）.md`（改编路径）
