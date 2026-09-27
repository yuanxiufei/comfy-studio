# comfy-studio

把两个上游项目就地打通成一个能用的工作台：

| 角色 | 上游仓库 | 在本仓的位置 | 装的自己人代码 | 落点 |
| --- | --- | --- | --- | --- |
| 后端 · 引擎 | [Comfy-Org/ComfyUI](https://github.com/Comfy-Org/ComfyUI) | `ComfyUI/` | skills / mcp / agent / HTTP 路由 | `custom_nodes/comfy_studio/` |
| 前端 · 桌面壳 | [Comfy-Org/Comfy-Desktop](https://github.com/Comfy-Org/Comfy-Desktop) | `Comfy-Desktop/` | MCP 宿主 / agent / 宿主进程接口 + 3 个主进程模块 | `lib/comfy_studio/`、`src/main/lib/` |

两份上游工作树**整份收在父仓库里**（`ComfyUI/`、`Comfy-Desktop/` 的每个文件都由父仓库跟踪），
因此它们自己没有 `.git` —— git 只可能把带 `.git` 的目录记成 gitlink，要把内容入库就必须把 `.git`
挪走（本机那份在 `.cache/upstream-git/<检出名>.git`，要恢复成独立检出就搬回去）。
装自己人代码用的都是它们各自的**标准扩展位**
（ComfyUI 认 `custom_nodes/`，桌面壳的 `lib/` 是它既有的 Python 脚本目录，会被打进 `extraResources`）。
除此之外的打通胶水（建环境 / 注册安装 / 单独起引擎 / 体检）也各自收在两侧自己代码的地盘里，
**规则是脚本跟着它作用的那个进程走**：只碰引擎的（建 venv、单独起引擎、单独起引擎侧 MCP）住引擎包
`custom_nodes/comfy_studio/tools/`；宿主与跨两侧的（注册安装、起宿主、清壳缓存、体检）住桌面壳自己的
脚本区 `Comfy-Desktop/scripts/comfy-studio/` —— 注意不是 `lib/comfy_studio/`：上游 eslint 只给
`./scripts/**` 的 js/mjs/cjs 配了 node 全局，`.mjs` 塞进 `lib/` 会被判成一片 `no-undef`。
根上只剩一份 `package.json` 当入口清单（`npm run doctor` 之类），脚本本体一行都不在根目录。

**自己人代码只有一份，就住在上面那两个扩展位里 —— 检出里的那份就是唯一事实源。**
（早先还有一层 `studio/overlay/` 副本加 `npm run attach` 单向同步，2026-09-27 撤掉了：副本就是
分叉源 —— 改了源忘了同步、或在下游就地改，两边会悄悄不一致。要翻那层旧账看 git 历史里的 `studio/`。）

每侧自己带一份**上游自述**，跟代码同处一地，人读的和脚本读的是同一份文件：

* `ComfyUI/custom_nodes/comfy_studio/upstream-baseline.json`
* `Comfy-Desktop/lib/comfy_studio/upstream-baseline.json`

字段：`checkout` / `repo` / `version` / `branch` / `commit` / `subject` / `placement`，桌面侧多一个
`patch`。`npm run seed` 靠引擎那份认出「这是哪份上游」（`ComfyUI/` 整份收在父仓里、自己没有 `.git`，
身份只能从自述读）；`npm run doctor` 靠它核对落点文件是否都已入库、接线补丁还在不在。
**上游升级后就改这两个文件里的基线。**

对上游既有文件的接线改动只有一处，是**补丁**而不是整份覆盖：

* `Comfy-Desktop/lib/comfy_studio/upstream-wiring.patch` —— 桌面侧 5 个文件、121 行
  （`packages/comfyui-desktop-bridge-types/comfyDesktopBridge.d.ts`、`src/main/host/attach.ts`、
  `src/main/lib/ipc/index.ts`、`src/preload/comfyPreload.ts`、`src/types/comfyDesktopBridge.ts`）。
  父仓里那 5 个文件是**已打上**的样子，补丁本身是"上游升级时怎么重放"的唯一依据：整份覆盖会在
  上游更新同一文件时静默把上游的改动顶掉，补丁在 `git apply --check` 阶段就失败、失败即报错。

改代码就直接改扩展位里那份（父仓跟踪，`git diff` 看得见），不经过任何中间层。

提交时留意检出里那些「藏着的」文件：引擎侧 `custom_nodes/` 被上游自己的 `.gitignore` 忽略，
当初就是靠 `git add -f` 逐个加进父仓的 —— 也正因为上游默认忽略它，`git status` 连新增文件都不显示，
最容易漏掉。`npm run doctor` 会机械核对这一条。

## 快速开始

```powershell
npm run setup          # 给 ComfyUI 建 .venv 并装依赖（GPU 版 torch）
npm run setup:desktop  # 装 Comfy-Desktop 的 Electron 依赖
npm run seed           # 把本仓 ComfyUI 注册成桌面的一个已有安装
npm run dev            # 起桌面壳
```

一条龙：`npm run setup:all && npm run dev`。

验证与排查：

```powershell
npm run doctor         # 四段式体检：自己人代码入库 / 引擎 / 桌面壳 / 接线，逐项通过或给出下一步命令
npm run engine         # 不经桌面壳单独起引擎（默认 127.0.0.1:8188）
npm run mcp            # 单独起引擎侧 MCP server（stdio），喂给外部 agent 客户端
npm run studio         # 单独起桌面侧 comfy-studio 宿主（MCP 客户端 + skill 目录 + 对话 agent）
```

## comfy-studio 三件能力

agent / skill / mcp 三件能力**前后端各有一份**，按各自项目里的标准位置放：

### 后端（`ComfyUI/custom_nodes/comfy_studio/`）

* `skills/` —— skill = 参数化的工作流模板（`skills/workflows/*.json`）+ 严格参数校验
  （`params.py`）+ 执行器（`runner.py`：注入参数 → 入队 → 等完成 → 收图片）。
  目录视图是可热重载的 `SkillRegistry`（内置目录 + 用户目录），所以对话里刚用
  `comfy_save_skill` 沉淀下来的 skill **同一个进程里立刻能跑**，不用重启。
* `mcp/` —— 把引擎能力开成 MCP server：9 个通用工具（模型类别 / 模型列表 / 提交工作流 /
  队列 / 历史 / 中断 / 列 skill / 跑 skill / 存 skill）外加每个 skill 一把 `skill__<id>`。
  模型那两把分工：`comfy_list_model_folders` 报本机注册了哪些类别（由引擎的
  `folder_paths` 决定 —— 除自带那些，第三方节点自己注册的目录也在内，所以不写死清单），
  `comfy_list_models` 拿类别名取具体文件。入口 `python -m comfy_studio.mcp`，
  cwd 必须是 `custom_nodes/`。
* `agent/` —— 对话式 agent 循环（OpenAI 兼容 tool calling），工具直接走进程内的引擎原语。
* `routes.py` —— 挂在 `/comfy-studio/*` 上的 HTTP 接口（skills / models / queue / interrupt /
  agent chat），供画布前端调用。

### 前端（`Comfy-Desktop/lib/comfy_studio/`）

* `mcp/` —— MCP **宿主**（与后端方向相反）：拉起引擎那个 server 并汇成一张工具表，
  顺带支持用户自己配的 server（环境变量 `COMFY_STUDIO_MCP_SERVERS`，JSON 数组）。
* `skills/` —— 走 MCP 读引擎的 skill 目录，变成面板能渲染的列表；不自己跑工作流。
* `agent/` —— 同一套对话循环，但工具来自 MCP 工具表，所以「宿主能连到的能力」与
  「对话能用的能力」永远一致。`catalog.py` 是面板那个智能体下拉的清单（内置的通用助手 +
  随包预置的 6 份完整规格 `agent/presets/*.md` + 用户放在数据目录 `agents/` 里的 `*.md`，
  见下面的「智能体那一栏」）。
* `server.py` / `rpc.py` / `__main__.py` —— 桌面壳拉起的进程接口：行分隔 JSON-RPC 2.0 over
  stdio（`stdout` 只跑协议，诊断走 `stderr`），`agent/chat` 过程中会推 `agent/event` 通知，
  让面板能边跑边画工具调用。
* `canvas.py` —— 画布通道（只有宿主侧有，因为画布在引擎前端页面里）：把 `canvas__snapshot`
  与 `canvas__load_workflow` 两个工具混进同一张 MCP 工具表（形状与 stdio client 一致，对话循环
  因此一行都不用改）。动作本身走一条回程：宿主推 `agent/event`（type `canvas_call`）→ 桌面壳在
  那个安装的画布页面里执行 → `agent/canvas_result` 把结果送回宿主等着的 future。没人接这条通道
  （例如直接拿 `run-mcp.mjs` 喂别的 MCP 客户端）时工具会明确回"等不到回音"，不假装读到一张空图；
  桌面壳启动宿主时带 `--canvas`，这张工具表才会出现。
* `channel.py` —— 上面那条「回程」的公共骨架（emit → 等 future → 超时/幂等回填），
  `canvas.py` 与 `review.py` 都是它的一种：两者只有工具名、id 前缀与超时不同。
* `review.py` —— 审核通道：`review__ask_user` 让 agent 在关键节点问用户（带选项）、
  **真的停住**等回答，回答经 `agent/answer` 回填；同一张卡片再答一次只会回 `delivered: false`
  （人答晚了不是错误）。桌面壳启动宿主时带 `--review`，工具表里才有它。
* `plan.py` —— 计划通道（灵感输入）：用户只给一句想法（“做张赛博朋克海报感的猫”）时，
  `plan__submit` 先拆成 2~8 步清单**交给用户过一眼**（面板画成清单卡：点「就按这个来」=
  `approved: true`；点「改一下」+ 写一句 = `approved: false` + `feedback`，两条都经
  `agent/plan_result` 回填）；用户点头后再用 `plan__progress` 逐步播报（running / done /
  failed / skipped），让清单上的那一步打上勾。进度那条走的是 `channel.py` 的**单向通知**
  （`notify`，不建 future）——播报不该再把一轮对话卡住。否掉却不说要改哪里会被两头挡住
  （面板就地提示 + 宿主回 -32602），免得模型瞎猜。桌面壳启动宿主时带 `--plan`。
* `localfiles.py` —— 本机文件衔接：`localfiles__import_file` 把用户指的本机素材接进
  ComfyUI 的 `input/`（返回能填进 `LoadImage.image` 那类字段的相对名 —— 加载类节点认不了
  磁盘绝对路径）、`localfiles__list_files` 报产出的**真实路径**（引擎的 history 只有
  filename）、`localfiles__read_text` 读本机文本。它不推事件、不等谁回话，只要
  `--comfyui-dir` 给了就挂上。这两个目录**由桌面壳按引擎自己的启动参数接上**
  （`comfyStudioHost.ts` 的 `resolveEngineStorageDirs`，规则与 `launch.ts` 的存储分支同源）：
  共享存储下引擎的 `--input-directory` 是 `Shared/input`，宿主要是自己按
  `<comfyui-dir>/input` 猜，接进去的素材引擎看不见、报出来的产出路径也不对。单独拿
  `run-mcp.mjs` 喂别的 MCP 客户端时才需要手动给 `--input-dir` / `--output-dir`
  （或 `COMFY_INPUT_DIR` / `COMFY_OUTPUT_DIR`）。
* `memory.py` —— 跨会话的长期记忆：对话正文会存盘（见下面的 `history.py`），但"我喜欢方形
  构图"、"这台是 24G 的 4090"这类**事实**不该指望别人去翻上一段对话，它们得是随叫随到的。
  这里用三张工具把它记下来：
  `memory__remember`（一条只说一件事，内容重复不会记两条）、`memory__recall`（不给关键词就
  列最近的，给了就只回匹配的）、`memory__forget`（删记错/过时的，id 从 recall 拿）。
  除了工具，它还会把 :meth:`MemoryStore.digest` 拼进**系统提示词**，而且
  `AgentSession.ask` 每轮重算一次 —— 这一轮刚记住的事，下一轮人设里就有，不用模型自己
  想起来去查；素材多了才靠 `memory__recall` 挑（提示词里只放最近 20 条 / 1200 字，超出的
  部分会如实写明"另有 N 条"）。它同样不推事件、不等谁回话，**默认就开着**：一份 JSON 落在
  用户数据目录（Windows `%APPDATA%\comfy-studio\memory.json`），`--memory-dir`（或
  `COMFY_STUDIO_MEMORY_DIR`）换地方，`--no-memory` 整个关掉。放在**用户目录**而不是
  ComfyUI 检出里是有意的：检出和 `.venv` 随时可以删掉重建，用户的记性不该跟着一起没。
  文件坏了（不是 JSON / 版本不认识 / 形状不对）会**报错而不是静默重建** —— 悄悄从空开始
  会变成"助手莫名其妙把记性丢了"，比报错难查；`host/info` 里会如实报出 `memory_file`、
  `memory_entries` 与 `memory_error`（记忆坏了也不挡握手，否则连"记忆坏了"这句话都传不到面板上）。
* `history.py` —— 对话正文的存档，与 `memory.py` 分工明确：记忆记**事实**（跨会话共享），
  这里记**对话**（按 session 分开）。一轮跑完就把整段对话写成一份 JSON（落在记忆目录下的
  `sessions/`，所以 `--memory-dir` 一换它跟着走），宿主下次起来建会话时把它喂回
  `AgentSession` 接着聊，面板重开时用 `agent/history` 拿回同一套条目重画。存的是用户话 /
  助手话 / 工具调用与结果，**人设（system）不存** —— 它每轮重算（记忆、在挂的通道都会变），
  存下来就是一份过期人设。写盘是原子的（临时文件 + `os.replace`），文件名取 session_id 的
  sha1 前 16 位（外面给的 id 拼不出 `../`）；读回来时只留**整轮**（第一条必须是用户话，不会
  出现"结果还在、调用被裁掉"）、超长内容截断并写明截了多少、工具调用与结果必须成对 —— 一轮
  里连着调好几次工具就一组一组地看（第二组来了第一组还欠着结果、末尾挂着没结果的调用，都算
  不成对）、对不上就整份拒绝并如实报错（假装"还没聊过"会让用户以为对话被吞了）；写盘前也走
  同一套检查，不成对的历史干脆不落盘（写下去等于亲手造一份下次打不开的存档，连更早那几个好
  轮次一起赔进去；这一轮少存一截只是历史缺了尾巴，答案早就交给用户了）。`agent/reset` 连存档
  一起删（只清内存的话，下次重启会被原样复活；有一轮在跑时先拒绝，否则那一轮收尾会把刚删掉的
  存档原样写回来），`--no-history` 整个关掉，`host/info` 里报出 `history` 与 `history_dir`。
  存档目录本身就是那份"你有几段对话"的清单：`agent/sessions` 把**活着的会话**与**存档里的会话**
  合成一段一行（标题取第一句用户话、条数、上次落盘时间、活没活着、在不在跑），同一段两边都在时
  以活着的那份为准（存档要到一轮末尾才写）；读不了的存档作为一行带 `error` 报出来并只认得出文件名
  —— 一个坏文件不该把所有对话从清单里抹掉，那会让用户连"换一段接着聊"都做不到。`agent/close`
  与 `agent/reset` 分工不同：close 只是**关掉这一段**（放掉它的连接、腾出会话位，对话留在存档里，
  下次用同一个 `session_id` 还会被喂回来），reset 是**清掉这段对话**（连存档一起删）。

对话要模型，配在环境变量里（不落盘、不进仓库）：`COMFY_STUDIO_LLM_MODEL`（必填）、
`COMFY_STUDIO_LLM_BASE_URL`、`COMFY_STUDIO_LLM_API_KEY`。没配的话 `agent/config` 会明确
告诉你缺什么，`agent/chat` 直接报错，不会假装能聊。

环境变量给的是**默认**模型；抽屉头上那个下拉可以在同一个 `base_url` 上换一个：

* `agent/models` —— 可选清单直接问服务端要（OpenAI 兼容的 `GET {base_url}/models`，
  Ollama / LM Studio / vLLM 都实现了这个口）。拉不到就不抛错，只回当前配置的那一个，
  并在 `error` 里说明原因、`source: "config"` 标明这份清单不是服务端给的。
* `agent/model` —— 不带 `model` 是读，带上就是切。切换是**宿主进程内**的：新会话直接用它，
  已经建好的会话也当场换成新客户端（历史保留），但正忙的会话会跳过并在 `skipped` 里报出来
  ——那会儿换客户端会把在飞的一轮打断。重启宿主就回到环境变量里的那个模型。

智能体那一栏换的是**角色段**，跟换模型是两件事（谁在答 / 用哪个模型答）：底座规则
（`agent/loop.py` 的 `BASE_SYSTEM_PROMPT`）不动，`agent/catalog.py` 的 `AgentCatalog` 给清单：

* `agent/agents` —— 三层拼出来的清单。**代码内置**（`BUILTIN_PROFILES`）只剩**通用助手**一项：
  不带任何角色段，就是出厂行为。**随包预置**（`PRESET_AGENTS` + `agent/presets/`，那边有自己的
  `README.md`）是 6 份**完整规格** —— 分镜导演助手、剧本创作、漫剧服化道、角色道具资产库、
  调音大师班、歌词创作，正文**整份**读进来当角色段（那些文档本来的用途就是整份塞进 System
  Prompt；每份 2.6–4.9 万字符，选中哪个才带哪个，但那一轮每一轮都带）。**用户自己的文件**放在
  工作台数据目录 `agents/`（`--agents-dir` 或 `COMFY_STUDIO_AGENTS_DIR`）里，一份文件一个智能体，
  形状是 `# 名字` + 紧随其后的 `> 一句说明` + 人设正文（文件名去掉 `.md` 就是 id，正文原样拼进
  系统提示词）。
  目录**每次现扫**，往里面丢一份 md 不用重启宿主；单个文件读不了不会拖垮整份清单，它作为一条
  带 `error` 的 `problems` 报出来（面板画成一条不可选的灰选项，免得用户以为自己那份文件没生效
  而反复改它）；预置读不了同理，只是 `file` 写成 `presets/<文件名>`，好分出是包里坏了还是自己的
  文件有问题。用户文件与**预置 id 相同**时就地顶掉它（预置是默认底稿，自己那份说了算），与
  **通用助手**重名则是一条错误（内置不该被顶）。目录整体读不了时，清单里只剩内置与预置 + `error`。
* `agent/agent` —— 不带 `agent` 是读，带上就是切。切之前先**验这个 id 在不在清单里**：不在就
  当场回 -32602（模型名可以随便写、合不合法服务端说了算；智能体 id 就是我们自己那份目录，
  写错只会在聊天时才炸）。切换**不跳过任何会话**，所以没有 `skipped` —— 人设是每轮重算的，
  正在飞的那一轮开头已经把提示词算好了，下一轮自然用新的。
* 换智能体**不动工具表、也不动对话历史**（历史里从来不含 system）：它换的是"这次是谁在干活"，
  不是"它能干什么"。重启宿主回到 `general`（一个字的角色段都不插）。

桌面壳里的入口：画布侧栏多一个 comfy-studio 按钮，点开是对话抽屉
（`Comfy-Desktop/src/main/lib/comfyStudioChatContentScript.ts`），
它经 preload 桥 `window.__comfyDesktop2.ComfyStudio` 走 IPC 找主进程，
主进程再按需 spawn 上面的宿主进程。抽屉顶部两个下拉：上面一行是模型，紧挨着的
一行是智能体；一轮在跑时两个都禁用（换哪个都会把在飞的一轮搅乱）；
旁边那个「停止」按钮走 `agent/cancel`——宿主立刻不再等模型与引擎，
这一轮回的是**正常结果**（`cancelled: true`）而不是错误，面板把它画成"已停止"，
历史配对完整，接着聊下一句就行。

这个抽屉和宿主是两套生命周期：页面刷新、换个画布、宿主进程退出又起来，对话都不该凭空消失。
所以打开抽屉（且里面还是空的）时，面板会问一次 `agent/history`：会话还活着就从它手里拿，
没有就读盘上那份存档，拿到的条目走的是**和实时事件同一套画法** —— 重开面板看到的是上次那段
对话，顶上那行小字写明"上次的对话（存在这台机器上）"，被裁掉的部分会标出"更早的 N 条没留下来"。
存档读不了（文件坏了 / 版本不认识）就画一行说明并写出文件在哪，而不是让用户对着空白猜。

模型下拉下面那行是**会话**：一段对话 = 一个 `session_id`，所以能换、能新开、能关掉。
下拉里就是宿主那份清单（`agent/sessions`），每行是"标题 · 条数"，当前那段带「（当前）」，
只在存档里的标「（存档里）」，正在跑的标「（在跑）」；读不了的存档列成一行不可选的
「读不了：<文件名>」（悬停给出原因），用户得先修或删它。切换会按那一段的存档重画（标题换成
「这一段对话」，空的那段写一句"这一段还没说过话"——用户刚点过来，得知道自己站在哪一段上）；
重画是异步的，手快点两下时前一段的历史可能后回来，所以每次清空都翻新一张"票"，回来对不上票
就一句都不画 —— 否则两段话会混在一屏上而下拉说的是另一段；清单读失败（宿主抖一下、或它刚
重启）时**保留上一份**、只在悬停里说明这次没读到，把下拉清空看着就是"别的对话都没了"；
「＋」用时间戳生成一个新 id 并清空抽屉（新的一段在说出第一句话之前宿主里根本没有它，也不占位子）；
「关掉」走 `agent/close`（腾位子，对话留在存档里，下次选它就能接着说），关掉之后面板接着开一段
新的 —— 关掉的意思是"这一段我聊完了"，不是"我要看着它空着"。`--no-history` 那一档没有存档兜底，
关掉就是真丢掉，所以要先点两下（第一次只警告），丢掉这件事只能由用户自己确认。有一轮在飞时这
三个控件都禁用（换走会把这一轮的回答画到别的对话上，关掉等于把活劈了，宿主那边也会拒）。
面板自己只往浏览器存储里记一个 id（`comfyStudio.session`：上次停在哪一段），对话本身在宿主那儿
—— 记不住（隐私模式等）会在悬停提示里说明这一屏重载后会回到默认那段，而不是假装记住了。

会话是**有数的**：宿主同时最多留 8 个活着的会话（每个握着一条连接和一份对话内存），到上限时
淘汰**最久没用过**的那个，而不是甩一个错误给用户（他只是想开个新对话）。敢这样做的理由是存档
兜底 —— 被淘汰的会话下次用同一个 `session_id` 建会话时会被存档喂回来，看到的还是上次那段。
正在跑一轮的会话一律不动（那一轮还在往里写，关掉等于把活劈了），只有**全都**在跑时才拒绝，
并在报错里说明卡在哪几个。`--no-history` 时没有这份兜底，淘汰就等于真把对话丢了，那就宁可不建
也不偷偷丢：照旧拒绝，并把原因写清（这一档下想腾位子只有两条路：复用 `session_id`，或者**用户
自己**点面板上的「关掉」—— `agent/close` 在这一档下等于丢掉那段对话，所以只能由用户点，宿主不
替用户点；`agent/reset` 只清对话、不腾位子）。`host/info` 里 `sessions` 是活会话名单、`busy` 是正在跑的。

面板上那行「它记在哪」是同一件事的另一半：开抽屉时会问一次 `host/info`，状态行下面就是一行小字 ——
记着几条事、对话存在这台机器上，完整路径放悬停提示里（那串路径铺在界面上要占掉半个抽屉）。
三种"看着像 bug、其实不是"的情况在这一行里直说：记忆读不了（`memory_error`）报红并写出是哪个
文件 —— 这一档下**每问一句都会报错**，因为人设每轮都要拿记忆重算，修好或删掉它才能接着聊；
宿主是 `--no-memory` / `--no-history` 起的也写明（"它这一档不记事" / "面板一关这段对话就没了"），
免得用户把配置当成坏了。宿主没报的字段不替它编，就报"没说"；一轮跑完再看一眼条数，刚记下的事
当场就能看见。

画布那两个工具既是给模型用的也是给用户用的：问"我这张图里有什么"，它会先
`canvas__snapshot` 看清再答；说"把这份工作流放到画布上"，就落到
`canvas__load_workflow`（它会替换当前画布，工具描述里写明了，模型会先说清楚再动手）。

用户本机的文件也是同一张表里的事：说"用 D:\图片\cat.png 当参考图"，模型会先
`localfiles__import_file` 把它接进 `input/`，再拿返回的名字去填 `LoadImage`；
问"刚生成的图存哪了"就用 `localfiles__list_files` 拿到盘上的真实路径，而不是拿
引擎给的 filename 拼。这些都不需要谁接话，也不写在代码里写死盘符 —— 目录一律
由 `--comfyui-dir` 推出来。

一句想法也一样：说"做张赛博朋克海报感的猫，海报感"，模型不会闷头自己编排到底，而是先用
`plan__submit` 拆出几步交给你过目（要好几步才能做完的事尤其如此）；你点了「就按这个来」，
它才开跑，并逐步用 `plan__progress` 在清单上打勾。已经在清楚地下命令（"用 SDXL 跑 4 张"）
就不用麻烦这一趟 —— 这条只用在"听得出要干什么、看不出该怎么落地"的时候。

它还认得你：说"记住我喜欢方形构图"，模型会 `memory__remember` 记下来（面板上就是一张
`memory__remember` 工具卡，返回的 id 写在结果里），**关掉面板、重启宿主、换一天再来**，
你问"你记得我什么"它照样答得出来 —— 那条偏好每轮都拼在系统提示词里，不必先查。想删就说
"忘掉那条方形构图的"，它会 `memory__recall` 找到 id 再 `memory__forget` 删掉。什么该记
（问过的偏好、惯用的模型和尺寸、这台机器的显卡）什么不该记（一次性的临时要求、密钥之类的
敏感信息、敏感内容）都写在那三张工具的描述里 —— 那是模型判断的唯一依据。记忆档就是
`%APPDATA%\comfy-studio\memory.json`（Linux/macOS 按各自惯例的用户数据目录），一个能直接
打开看的 JSON，想清空就关掉宿主把文件删了。

## 打通是怎么做到的

除了上面新增的扩展位，胶水本身靠的是 Comfy-Desktop 自己就支持「接管一份已有的引擎检出 + 目录里的 venv」这个能力：

1. **引擎侧**：`ComfyUI/custom_nodes/comfy_studio/tools/install-engine.ps1`（`npm run setup`）在 `ComfyUI/.venv` 建 Python 3.11 环境，装 CUDA 版 torch（本机有 N 卡时；否则回退 CPU 轮子）和上游 `requirements.txt` 的其余依赖。
2. **接线侧**：`Comfy-Desktop/lib/comfy_studio/tools/seed-desktop.mjs`（`npm run seed`，`npm run dev` 会先跑它）往 Comfy-Desktop 的安装清单
   （Windows：`%APPDATA%\comfyui-desktop-2\installations.json`）写一条 `sourceId: "git"` 的记录：
   `installPath` 是**仓库根**，`venvPath` 指着 `ComfyUI/.venv` —— 壳认的布局是「安装根下套一个
   `ComfyUI/` 子目录、venv 在 `ComfyUI/.venv`」，和上游 git 检出长得一样，于是本仓 `ComfyUI/` 与它的 `.venv` 都被认到。
   起引擎那条路是 `<venvPath>/Scripts/python.exe -s main.py <launchArgs>`，cwd 取 `main.py`
   所在目录 —— 只用 `venvPath` 与 `main.py`，不读 `.git`，所以本仓这种已入库的检出照样能被拉起。
   注意 comfy-studio 宿主（`Comfy-Desktop/lib/comfy_studio`）不走这条路：它按 `<installPath>/ComfyUI/.venv`
   派生 python（`Comfy-Desktop/src/main/lib/pythonEnv.ts` 的 `getVenvPythonPath`），不读 `venvPath`；
   `installPath` 写偏一层时，引擎照起、面板却整片报「没有可用的 venv python」。`npm run doctor`
   （脚本在 `Comfy-Desktop/lib/comfy_studio/tools/doctor.mjs`）的「接线」段会把这条路单独核一遍。
   上游源码里 `.git` 只被 `probeInstallation`（UI 里「添加已有安装」那条路）和详情页的 git 动作用到，
   我们直接写记录、不经过前者，代价是后者对本仓这个安装不可用。
   有了这条记录，首启的「用云端还是本地」向导也会被跳过（列表里已有非 cloud 安装）。
3. **前端侧**：桌面壳启动引擎后，窗口直接加载引擎自带的画布
   （`comfyui_frontend_package`，ComfyUI 1.53.6 前端包由 pip 装进引擎 venv）。

## 已知取舍

- **模板全家桶要单独走官方 PyPI**：`ComfyUI/requirements.txt` 钉的
  `comfyui-workflow-templates==0.11.70` 硬依赖 `media-assets-02==0.1.6` 等 6 个 media
  缩略图包，而本机默认 pip 源（清华镜像）只同步了其中 5 个、唯独 `media-assets-02` 是
  404，会让整份清单解析失败。安装脚本把模板那一行剔出来，改用官方
  `pypi.org/simple` 一次性装全家桶（薄封装 + core + json + 6 个缩略图包，约 500 MB），
  保证模板数据和缩略图都齐全 —— 否则前端模板库会因缩略图 404 而整片空白。
- **`bootstrap-python` 未构建**：Comfy-Desktop 的 `predev` 会提示，
  它只影响「桌面内建 python 去 clone 新安装」那条路，跟我们这套「接管已有检出」无关，忽略即可。
- **上游内容入库的代价**：`ComfyUI/` 与 `Comfy-Desktop/` 现在整份由父仓库跟踪（约 74 MB / 2200 个文件），
  clone 一次就自带、不依赖上游可达；代价是这两个检出不再是独立 git 检出 —— 不能在本仓里 `git pull`
  上游，仓库历史里也没有上游的提交记录。
- **上游升级的路径**（这两份检出没有 `.git`，不能就地 `git pull`）：另 clone 一份上游到临时目录，按需把
  内容搬进来替换，改那一侧 `upstream-baseline.json` 的 `version` / `commit` / `branch` / `subject`，
  再拿两条 `git apply` 试跑看补丁还合不合得上：

  ```powershell
  # 能退掉 = 补丁已经打上（应该这样）
  git -C Comfy-Desktop apply --check --reverse Comfy-Desktop/lib/comfy_studio/upstream-wiring.patch
  # 能打上 = 还没打（刚换过上游内容、还没重放补丁）
  git -C Comfy-Desktop apply --check Comfy-Desktop/lib/comfy_studio/upstream-wiring.patch
  ```

  两条都失败 = 上游把那几个文件改过了：`git -C Comfy-Desktop diff -- <文件>` 看清哪几处是我们的，
  人工并回那 5 个文件并更新补丁，最后跑 `npm run doctor`（它会把这个状态报成 `conflict`）。
- **账本只有三个文件，全在自己人代码里**：两侧各自的 `upstream-baseline.json` 加桌面侧那份
  `upstream-wiring.patch`。它们不参与运行，只在「换上游 + 重放补丁」这一刻兑现价值 ——
  另开一层账本目录的代价，是多一份要跟着同步的东西。

## 目录

```
comfy-studio/
├─ package.json      # 只有入口清单：npm run setup / setup:all / seed / dev / engine / mcp / studio / doctor
├─ ComfyUI/          # 上游引擎：工作树整份入库
│  └─ custom_nodes/comfy_studio/       # 引擎侧自己人代码：skills / mcp / agent + routes
│     ├─ tools/                        # 只碰引擎的脚本：建 venv / 单独起引擎 / 单独起引擎侧 MCP
│     ├─ upstream-baseline.json        # 这棵树上压的是哪份上游（seed / doctor 读它）
│     └─ tests/                        # 引擎侧自检（skills / 工具表 / 组合 / 路由 / stdio 协议）
├─ Comfy-Desktop/    # 上游桌面壳：工作树整份入库
│  ├─ lib/comfy_studio/                # 桌面侧自己人代码：mcp（宿主）/ skills / agent / 通道 + 宿主进程接口
│  │  ├─ upstream-baseline.json        # 这棵树上压的是哪份上游（placement 记着下面两处落点）
│  │  ├─ upstream-wiring.patch         # 对上游既有文件的接线改动（5 个文件 / 121 行）
│  │  └─ tests/                        # 宿主端到端测试（真进程 + 真 MCP 子进程）
│  ├─ scripts/comfy-studio/            # 宿主与跨两侧的脚本：注册安装 / 起宿主 / 清壳缓存 / 体检
│  └─ src/main/lib/                    # 面板注入脚本 / 宿主拉起 / IPC 注册（新增的 TS）
└─ .cache/           # 过滤清单、自检输出、安装日志，以及两份上游的 .git（父仓库忽略）
```

两组自检都直接在检出里跑（自己人代码就住在那里），不需要先装什么。

引擎侧（custom node）的自检，用引擎自己的 venv，不需要引擎在跑：

```powershell
cd ComfyUI/custom_nodes
..\.venv\Scripts\python.exe -m unittest discover -s comfy_studio/tests -t . -v
```

覆盖：skill 模板与参数的严格校验（坏文档逐条显式报错）、参数注入与 seed 随机化、
模型列表探测的错误分支、MCP 工具表与每个 handler、agent 循环（工具调用/失败回填/
步数耗尽）、以及 `/comfy-studio/*` 的 HTTP 契约。`test_mcp_stdio.py` 会真起
`python -m comfy_studio.mcp` 子进程喂 JSON-RPC，顺带守住「stdout 上只跑协议」这条纪律。

桌面侧宿主的行为验证（需要同一仓库的 ComfyUI 检出与它的 venv，缺了整组跳过）：

```powershell
cd Comfy-Desktop/lib
..\..\ComfyUI\.venv\Scripts\python.exe -m unittest comfy_studio.tests.test_host_e2e -v
# 纯逻辑用例（本机文件 / 计划通道 / 长期记忆 / 对话存档，不拉子进程）：
# test_local_files.py、test_plan_tools.py、test_memory_tools.py、test_history.py
..\..\ComfyUI\.venv\Scripts\python.exe -m unittest discover -s comfy_studio/tests
```

它用本地假模型服务顶替真 LLM（顺带提供 `GET /models`）：第一轮让模型要一次
`comfy_list_skills`，第二轮给结论，以此确认「agent 真的经 MCP 工具拿了引擎的数据」，
另外还验了模型清单与切换（切完之后请求体里的 `model` 真的变了）、智能体清单与切换
（切完之后下一轮请求体里的 system 提示词真的换了那段角色，`test_agents_tools.py` 再把
目录层钉住：内置项都在、随包预置 6 份都在且正文与文档一字不差、预置文件少一份或多一份都被
报出来、md 的三块怎么读、空正文/重名/读不了各自怎么报、自己的文件顶掉同 id 的预置、每次现扫
看得见新文件、选中的那份文件不见了会在聊天时明确报错而不是悄悄退回），全程不联网。
回程那三条通道各有端到端用例：审核（问完真的停住等人答）、本机素材进出（素材真落进
`input/`、产出报回盘上的真实路径）、计划（一句想法拆成清单等人点头、点头后才逐步播报），
测试自己就是那个"桌面壳"，收事件再按 RPC 把结果送回去。
长期记忆那条也一样：这一轮说"记住…"（假模型真的调 `memory__remember`），断言 `memory.json`
里确实多了那条（换个进程再读也在）、`host/info` 如实报出文件与条数，下一轮**不调任何工具**
也答得出 —— 也就是"每轮重算人设"这条路真通了（真假模型的系统提示词里都带着它）。
e2e 壳启动宿主时给记忆目录一个临时目录（`--memory-dir`），免得测试去动开发机上真人那份。
`test_memory_tools.py` 另外把存储层的硬约束钉住：重复内容不记两条、条数上限满了明确拒绝、
`recall` 只读不写盘、坏文件报错且原样留着不重建、提示词那段的条数与字数上限、以及
`compose_system_prompt` 里收尾要求永远在最后一条。
对话存档也一样有端到端的那一半：一轮跑完后断言盘上真的多了一份这个会话的存档（人设不在里面）、
`agent/history` 拿回的条目首尾对得上；`test_history.py` 再把存档自己的硬约束钉住 ——
换个进程也读得到、`../` 拼不出目录、只留整轮、超长内容截断并写明、工具调用与结果必须成对
（含"第二组调用来了、第一组还没结果"与"末尾挂着没结果的调用"这两种最像样的半截）、不成对的
历史连写都不写（不落盘）、坏文件/旧版本/别的会话的档一律报错且原样留着、`agent/reset` 连存档
一起清、写盘失败只 warning
（答案已经给用户了，不该因为存档写不进去把这一轮判成失败）。会话位满了也有三条用例钉着：
淘汰最久没用且空闲的那个（并且被淘汰的能从存档接回来）、正在跑的会话不动、`--no-history` 下
宁可不建也不偷偷丢。多段对话那两下同样是两层：e2e 真起宿主问一次 `agent/sessions`（标题、条数、
`max_sessions`、`live`）再 `agent/close` 掉一段，断言它从"活着"变成"只在存档里"、再关一次不算错、
接着说一句还能被喂回来；`test_history.py` 再钉住清单自己的硬约束 —— 标题取第一句用户话（压成一行
并截断）、没存过的会话与空会话不出现在清单里、最近的排前面、同一份目录列两次顺序一样、坏文件/没写
`session_id` 的文件作为带 `error` 的行报出来且其余照旧可切、关掉腾位子但存档还在（同一个 id 能接回来）、
关掉一个本来就没开着的会话不算错、有一轮在跑时拒绝关掉、`--no-history` 下 `history_kept: false`。
桌面壳自己的 TypeScript 侧测试走 `pnpm test`（新增面板脚本的用例在
`src/main/lib/comfyStudioChatContentScript.test.ts`，含模型下拉：填充、切换、
被拒时回滚、一轮在飞时禁用；智能体下拉同一套（填充、切换并点明"下一次提问生效"、被拒时回滚、
读不了的文件画成灰选项、选中的那份不见了就如实空着不假装选中、一轮在飞时禁用）；
以及审核卡与计划清单卡：画清单、点头/要改、进度打勾；
还有"回到上次的对话"：开抽屉时照存档重画、被裁条数的提示、档读不了画一行说明、抽屉里
已经有内容就不再补一遍；以及"它记在哪"那一行：记着几条 + 存在这台机器上（路径在悬停里）、
记忆读不了报红并写出文件、`--no-memory` / `--no-history` 各自写明、宿主没报的字段报"没说"、
一轮收尾后重读条数；以及那行**会话**：开抽屉认回"上次停在哪一段"（并说清记不住的情况）、
把宿主清单画成下拉（当前/存档里/在跑各自的标法、读不了的那行不可选）、换一段按存档重画、
空的那段写一句"还没说过话"、新开一段换新 id 且下一句落到新 id 上、关掉之前先问一次
（`--no-history` 下要点两下才真关）、关掉之后接着开一段新的、一轮在飞时三个控件都禁用、
换段时迟到的响应一句都不许画、刷新清单失败保留上一份、关掉之后还能从下拉选回来接着说、
浏览器存储读不了时如实说明（退回默认那段而不是装作记得）；
长期记忆没加面板代码：`memory__remember` / `__recall` / `__forget` 就是普通工具调用，
抽屉里那套工具卡本来就会把参数与返回的 id 画出来 —— 另起一条提示条是同一份信息的重复）。
