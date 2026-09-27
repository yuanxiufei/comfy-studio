# 规格原文归档 · 索引

> 本目录存放**用户提供的蓝图原文**，是 `../`（智能体运行时）的来源。
>
> **原文一律保留，不删除**——实现是日常工具，原文是细节依据与追溯凭证。

**归档时间**：2026-09-24　**来源**：`data/智能体搭建参考md/AI资产库角色道具智能体/`

---

## 一、为什么保留原文

| 用途 | 说明 |
|---|---|
| **查细节依据** | 实现为可用性做了取舍；具体参数、完整示例仍在原文 |
| **追溯来源** | 确认某个规则来自用户蓝图还是自行补充 |
| **防止信息损失** | 实现必然有取舍；原文是"无害化备份" |
| **重做时不必再找** | 蓝图只在用户工作区里，换机器/换人后容易失联 |

> ⚠️ **权威顺序**：两者冲突时以**原文**为准；**日常使用以实现为准**。

---

## 二、原文清单（4 份）

| 归档名 | 体积 | 说明（含原文件名） |
|---|---|---|
| `01-项目架构蓝图.md` | 8.0 KB | 23 节 · 项目目录 / 七个 Agent / ID 系统 / 迁移 / API Key；原 `AI漫剧资产库_Agent_—_CodeBuddy_项目架构.md` |
| `02-SYSTEM_PROMPT原文.md` | 11.6 KB | 30 节 · Agent 身份 / 补全规则 / Prompt 生成 / 核心执行指令；原 `SYSTEM_PROMPT.md` |
| `03-README原文.md` | 4.2 KB | 11 节 · 使用方式 / 跨机迁移 / 修改已有资产 / 跨平台原则；原 `README.md` |
| `04-config与模板与规则与示例原文.md` | 6.1 KB | config / Prompt 模板 / 角色规则 / 4 个示例 / 执行流；原名过长（`config.json` + 三份模板以 `+` 连接） |

> ℹ️ 体积列**故意不与「原文件名」相邻** —— 检查 8 的体积声明识别是
> 「`` `文件名` ｜ N KB ``」，若原文件名后面紧跟数字，它会拿**原文的**体积去比对
> **实现文件**（`SYSTEM_PROMPT.md` 有两个同名文件），必然误报。实测踩到过一次。

> 归档时仅做**行尾归一为 LF**（仓库 `.gitattributes` 口径），内容**逐字节保留**。
> 原文件名含 `| _ +` 等字符，不便引用，故改为可引用的编号名并在本表登记原名。

**另 6 份参考 md 已在工作流内**（无需重复归档，本表的对应关系便于追溯）：

| 用户参考 md | 工作流内位置 |
|---|---|
| `AI剧本创作_完整迁移配置.md` | `01-剧本文本/_规格原文/AI剧本创作-完整规格原文.md` |
| `AI漫剧服化道智能体_完整迁移配置.md`（旧版 `…_FULL_PORTABLE_AGENT_SPEC_V2.md`） | `02-服化道/00-主控智能体.md` |
| `AI漫剧资产库角色道具_完整迁移配置.md` | `02-服化道/_规格原文/AI漫剧资产库-完整规格原文.md` |
| `分镜导演助手_完整迁移配置.md` | `03-分镜导演/_规格原文/分镜导演助手-完整规格原文.md` |
| `Suno歌词大师_完整迁移配置.md` | `05-音乐音频/_规格原文/Suno歌词大师-完整规格原文.md` |
| `调音大师班_完整迁移配置.md` | `05-音乐音频/_规格原文/调音大师班-完整规格原文.md` |

---

## 三、章节落点索引

### 3.1 `01-项目架构蓝图.md`（23 节）

| 蓝图节 | 落点 |
|---|---|
| 一、项目目录 | `../README.md` §五 目录结构（**扩展为 7 agent 通用运行时**） |
| 二·1 Router Agent | `../src/dispatcher.py`（意图/模块路由）+ `../src/registry.py`（声明式注册表） |
| 二·类型判定 | `../src/nl_parser.py::_detect_asset_type`（含「量词+宾语」判据） |
| 三、Character Agent | `../src/character_agent.py`（11 题材预设，中英双语） |
| 四、Prop Agent | `../src/prop_agent.py` |
| 五、Costume Agent | `../src/costume_agent.py` |
| 六、Consistency Agent | `../src/consistency.py` + `../src/schema.py::fingerprint()` |
| 七、Prompt Agent | `../src/prompt_engine.py` |
| 八、资产 ID 系统 | `../src/schema.py` + `../src/asset_manager.py` + `../config/id_registry.json`（**前缀改采工作流规范**，见 §四·1） |
| 九、角色资产数据 | `../src/schema.py`（`VisualDNA` / `FixedFeatures` / `StageVariables`） |
| 十、版本控制 | `../src/asset_manager.py::save/next_version`（**统一三位** `v001`） |
| 十一、Prompt 文件 | `../output/prompts/<ID>/`（gitignored，可重算） |
| 十二、图片文件 | `../src/image_provider.py` + `../output/images/<ID>/` |
| 十三、Metadata | `../output/metadata/<ID>.json` · 通用 agent 另有 `../output/<agent>/meta.json` |
| 十四、用户交互 | `../main.py` CLI（**扩展**：`agents/init/run/route/handover/gate/doc/outline`） |
| 十五、后续修改 | `../src/agent.py::_apply_changes`（改一处、指纹锁其余） |
| 十六、角色调用 | `python main.py "<描述>"` 或 `run asset "<描述>"` |
| 十七、资产库查询 | `main.py::cmd_list` / `cmd_show` |
| 十八、批量生产 | ❌ **未实现**（`../README.md` §八 已诚实标注） |
| 十九、导出 | `main.py::cmd_export`（资产 ZIP + 规则快照） |
| 二十、跨电脑迁移 | `../README.md` §八 · `export --snapshot` · live/snapshot 双模式 |
| 二十一、API Key | `../.env.example` + 延迟 import（**Key 绝不入库**） |
| 二十二、未来模型适配 | `../src/llm_client.py`（任何 OpenAI 格式服务） |
| 二十三、最终目标 | 已达成，并**泛化**为 7 个 agent 的通用运行时 |

### 3.2 `02-SYSTEM_PROMPT原文.md`（30 节）

| 原文节 | 落点 |
|---|---|
| 1 Agent 身份 | `../SYSTEM_PROMPT.md` §1 |
| 2 核心工作原则 | §2（补 §2.3「唯一例外」） |
| 3 角色资产默认输出形式 | §4 |
| 4 默认画面规格 | §4 |
| 5 风格系统 | → **工作流权威层** `02-服化道/引擎/TURNAROUND-STANDARD.md`（不重复） |
| 6 角色补全规则 | §6.1 + `../src/character_agent.py` 预设表 |
| 7 材质描述规则 | §6.3 + `prompt_engine` MATERIALS 段 |
| 8 配色规则 | §6.4 + `character_agent` COLOR 字段 |
| 9 装备一致性 | §5 装备一致性铁则 + `../src/consistency.py` |
| 10 三视图规则 | §5 + `TURNAROUND-STANDARD.md`（权威） |
| 11 姿态规则 | §5 |
| 12 左侧特写规则 | §4 版式 |
| 13 背景规则 | `prompt_engine._tail_block` BACKGROUND 段 |
| 14 光影规则 | `_tail_block` LIGHTING 段 |
| 15 Prompt 生成规则 | `../src/prompt_engine.py::build_prompt_en` |
| 16 Prompt 语言 | §7.1（**严禁中英混排**） |
| 17 Prompt 结构（14 段） | `prompt_engine` 的 14 段输出 |
| 18 Negative Prompt | → **工作流权威层** `NEGATIVE-PROMPT-LIBRARY.md`（不重复；检查器钉住） |
| 19 图像生成行为 | `../src/image_provider.py`（mock/openai/stability） |
| 20 信息不足时 | §2.1 |
| 21 用户指定内容优先级 | §2.2 |
| 22 输出原则 | §9 |
| 23 道具资产扩展 | `../src/prop_agent.py` |
| 24 角色 + 道具 | `../src/agent.py` 编排 |
| 25 资产库一致性 | `../src/consistency.py` + `asset_manager` |
| 26 修改指令 | `../src/agent.py::_apply_changes` |
| 27 最终目标 | §12 |
| 28 默认最终 Prompt 模板 | `prompt_engine._tail_block` |
| 29 默认禁止 | §10 |
| 30 **核心执行指令** | §12（该关键词由工作流检查器的机制规则钉住，防被删） |

### 3.3 `03-README原文.md`（11 节）

重写为 7-agent 通用形态的 `../README.md`，**保留**其全部立场：
零依赖可跑 · 跨机迁移 · 「用户不需要使用固定格式」· 修改已有资产 · 跨平台原则 · 图像生成。

### 3.4 `04-config与模板与规则与示例原文.md`

| 原文部分 | 落点 |
|---|---|
| `config.json` | `../config.json` |
| `PROMPT_TEMPLATE.md` | `../src/prompt_engine.py` |
| `CHARACTER_RULES.md`（一致性/服装层级/配色层级/材质层级） | `../src/character_agent.py` + `consistency.py` |
| `EXAMPLES.md` 4 例 | `../examples/*.json` + 实跑用例 |
| `Agent Execution Flow` | `../src/agent.py::handle` · `../src/runtime.py::run` |
| `Final Principle` | `../SYSTEM_PROMPT.md` §12 |

---

## 四、⚠️ 实现对原文的 3 处**有意偏离**（必须登记）

### 4.1 资产 ID 前缀：蓝图 `CHAR-001` → 实现 `CHR_001`

蓝图用 `CHAR-` / `PROP-` / `COSTUME-` / `SCENE-`；而**工作流权威规范**
（`00-总控路由.md` §四）是 `CHR_` / `CST_` / `PRP_` / `ENV_`，
且 `02-服化道/01-资产库出图引擎.md` §〇.3 明文「**不得自造前缀**」。

**裁决**：采用工作流规范（架构对齐：与项目既有规范冲突时以既有规范为准）。
`config.json` 的 `id_style` 保留两套字面（`project` / `blueprint`），**语义完全相同**。

### 4.2 权威层不重复：蓝图的「风格系统 / 负面词 / 三视图硬标准」不在代码里复制

它们**已存在于工作流** `02-服化道/引擎/`。若在代码里再写一份，将来改工作流时
**没有任何机制会提醒同步代码** —— 这正是工作流质量守则 §2「单一权威来源」要防的事。
故由 `../src/rule_source.py` **运行时只读加载**。

### 4.3 泛化：蓝图只描述「02 资产库」，实现承载 7 个流程 agent

用户后续要求「工作流下面每个流程都是**独立的 agent**，**要通用**」。
故新增 `../src/registry.py`（声明式注册表）等 5 个通用模块，
把「资产库 Agent」泛化为**承载 00-06 全部流程 agent 的运行时**。
02 是唯一带**结构化超能力插件**的 agent（资产卡 + 出图 + 指纹锁定）。
