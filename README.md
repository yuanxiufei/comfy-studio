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
除此之外的打通胶水收在 `setup/` 里。

**自己人代码的源全部住在 `studio/`**（父仓库跟踪），由 `npm run attach` 装进上面那些扩展位：

* `studio/overlay/ComfyUI/`、`studio/overlay/Comfy-Desktop/` —— 按检出名分两侧，树形与落点一一对应。
* `studio/patches/Comfy-Desktop/0001-comfy-studio-wiring.patch` —— 对上游既有文件的接线改动
  （桌面侧 5 个文件、121 行）。用补丁而不是覆盖整份文件：上游更新同一文件时 `git apply --check`
  会当场失败并报错，而不是静默把上游的改动顶掉。
* `studio/upstream.json` —— 入库内容对应的上游 commit / 分支 / 版本。已入库形态下没有检出 HEAD 可对，
  上游有没有动过就看父仓的 `git diff`；若把 `.cache/upstream-git/<检出名>.git` 搬回去恢复成独立检出，
  `attach` / `doctor` 会改用检出 HEAD 核对，漂移就拒绝执行，要显式跑 `npm run attach -- --rebaseline`
  才重新对齐。

自己人代码有两重身份：检出里的那份是「跑起来的样子」（父仓库跟踪），`studio/` 里的是它的源。
改代码请改 `studio/`，再跑 `npm run attach` 同步（幂等）；直接在检出里改，`attach` 与 `npm run doctor`
会把「被就地改过」显式报出来，不会静默覆盖。确认无误后把 `studio/` 与检出一起提交。

提交时留意检出里那些「藏着的」文件：引擎侧 `custom_nodes/` 被上游自己的 `.gitignore` 忽略，
当初就是靠 `git add -f` 逐个加进父仓的 —— 也正因为上游默认忽略它，重建这棵树时最容易漏掉。

## 快速开始

```powershell
npm run setup          # 给 ComfyUI 建 .venv 并装依赖（GPU 版 torch）
npm run setup:desktop  # 装 Comfy-Desktop 的 Electron 依赖
npm run attach         # 校对自己人代码在检出里就位（幂等；改了 studio/ 之后跑它同步）
npm run seed           # 把本仓 ComfyUI 注册成桌面的一个已有安装
npm run dev            # 起桌面壳
```

一条龙：`npm run setup:all && npm run attach && npm run dev`。

验证与排查：

```powershell
npm run doctor         # 四段式体检：覆盖层 / 引擎 / 桌面壳 / 接线，逐项通过或给出下一步命令
npm run attach -- --check   # 只看覆盖层现在是什么状态、会装什么，不动盘
npm run detach         # 只对独立检出有效：把覆盖层与补丁撤出去（已入库形态会拒绝并给出替代命令）
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
* `mcp/` —— 把引擎能力开成 MCP server：8 个通用工具（模型列表 / 提交工作流 / 队列 /
  历史 / 中断 / 列 skill / 跑 skill / 存 skill）外加每个 skill 一把 `skill__<id>`。
  入口 `python -m comfy_studio.mcp`，cwd 必须是 `custom_nodes/`。
* `agent/` —— 对话式 agent 循环（OpenAI 兼容 tool calling），工具直接走进程内的引擎原语。
* `routes.py` —— 挂在 `/comfy-studio/*` 上的 HTTP 接口（skills / models / queue / interrupt /
  agent chat），供画布前端调用。

### 前端（`Comfy-Desktop/lib/comfy_studio/`）

* `mcp/` —— MCP **宿主**（与后端方向相反）：拉起引擎那个 server 并汇成一张工具表，
  顺带支持用户自己配的 server（环境变量 `COMFY_STUDIO_MCP_SERVERS`，JSON 数组）。
* `skills/` —— 走 MCP 读引擎的 skill 目录，变成面板能渲染的列表；不自己跑工作流。
* `agent/` —— 同一套对话循环，但工具来自 MCP 工具表，所以「宿主能连到的能力」与
  「对话能用的能力」永远一致。
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
  `--comfyui-dir` 给了就挂上；换过引擎的 `--input-directory` / `--output-directory` 时
  用 `--input-dir` / `--output-dir`（或 `COMFY_INPUT_DIR` / `COMFY_OUTPUT_DIR`）跟着指。

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

桌面壳里的入口：画布侧栏多一个 comfy-studio 按钮，点开是对话抽屉
（`Comfy-Desktop/src/main/lib/comfyStudioChatContentScript.ts`），
它经 preload 桥 `window.__comfyDesktop2.ComfyStudio` 走 IPC 找主进程，
主进程再按需 spawn 上面的宿主进程。抽屉顶部就是上面那个模型下拉，
一轮在跑时它是禁用的；旁边那个「停止」按钮走 `agent/cancel`——宿主立刻不再等模型与引擎，
这一轮回的是**正常结果**（`cancelled: true`）而不是错误，面板把它画成"已停止"，
历史配对完整，接着聊下一句就行。

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

## 打通是怎么做到的

除了上面新增的扩展位，胶水本身靠的是 Comfy-Desktop 自己就支持「接管一份已有的引擎检出 + 目录里的 venv」这个能力：

1. **引擎侧**：`setup/install-engine.ps1` 在 `ComfyUI/.venv` 建 Python 3.11 环境，装 CUDA 版 torch（本机有 N 卡时；否则回退 CPU 轮子）和上游 `requirements.txt` 的其余依赖。
2. **接线侧**：`setup/seed-desktop.mjs` 往 Comfy-Desktop 的安装清单
   （Windows：`%APPDATA%\comfyui-desktop-2\installations.json`）写一条 `sourceId: "git"` 的记录，指向本仓 `ComfyUI/` 与它的 `.venv`。
   该来源插件的启动命令是 `<venvPath>/Scripts/python.exe -s main.py <launchArgs>`，cwd 取 `main.py`
   所在目录 —— 这条路只用 `venvPath` 与 `main.py`，不读 `.git`，所以本仓这种已入库的检出照样能被拉起。
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
  上游，仓库历史里也没有上游的提交记录。要更新上游：另 clone 一份到临时目录，按需把内容搬进来，
  改 `studio/upstream.json` 的基线，再跑 `npm run doctor` 核对补丁还合不合得上。
- **`detach` 只对独立检出有效**：已入库形态下父仓里那份就是「装了覆盖层」的工作形态，撤出会把它删成
  一片删改，所以脚本直接拒绝并给替代命令（要纯净上游就另 clone 到临时目录）。

## 目录

```
comfy-studio/
├─ studio/           # 自己人代码的源（父仓库跟踪，靠 npm run attach 装进检出）
│  ├─ upstream.json                             # 入库内容对应的上游 commit / 分支 / 版本
│  ├─ overlay/ComfyUI/custom_nodes/comfy_studio/  # 引擎侧：skills / mcp / agent + routes
│  │  └─ tests/                                 # 引擎侧自检（skills / 工具表 / 组合 / 路由 / stdio 协议）
│  ├─ overlay/Comfy-Desktop/lib/comfy_studio/     # 桌面侧：mcp（宿主）/ skills / agent + 宿主进程接口
│  │  └─ tests/                                 # 宿主端到端测试（真进程 + 真 MCP 子进程）
│  ├─ overlay/Comfy-Desktop/src/main/lib/       # 面板注入脚本 / 宿主拉起 / IPC 注册（新增的 TS）
│  └─ patches/Comfy-Desktop/                    # 对上游既有文件的接线改动（补丁）
├─ setup/            # 打通物料：attach / detach / 装环境 / 注册安装 / 体检 / 单独起引擎(engine) / mcp / studio
│  └─ lib/overlay.mjs                           # 覆盖层装配与基线核对（attach / detach / doctor 共用）
├─ ComfyUI/          # 上游引擎：工作树整份入库（自己人代码在 custom_nodes/comfy_studio/）
├─ Comfy-Desktop/    # 上游桌面壳：工作树整份入库（自己人代码在 lib/comfy_studio/ 与 src/main/lib/）
└─ .cache/           # 过滤清单、自检输出、安装日志、被顶掉/删除内容的备份，以及两份上游的 .git（父仓库忽略）
```

两组自检都要求自己人代码已经装进检出（没装会直接「找不到包」），先跑一次 `npm run attach`。

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
# 纯逻辑用例（本机文件 / 计划通道，不拉子进程）：test_local_files.py、test_plan_tools.py
..\..\ComfyUI\.venv\Scripts\python.exe -m unittest discover -s comfy_studio/tests
```

它用本地假模型服务顶替真 LLM（顺带提供 `GET /models`）：第一轮让模型要一次
`comfy_list_skills`，第二轮给结论，以此确认「agent 真的经 MCP 工具拿了引擎的数据」，
另外还验了模型清单与切换（切完之后请求体里的 `model` 真的变了），全程不联网。
回程那三条通道各有端到端用例：审核（问完真的停住等人答）、本机素材进出（素材真落进
`input/`、产出报回盘上的真实路径）、计划（一句想法拆成清单等人点头、点头后才逐步播报），
测试自己就是那个"桌面壳"，收事件再按 RPC 把结果送回去。
桌面壳自己的 TypeScript 侧测试走 `pnpm test`（新增面板脚本的用例在
`src/main/lib/comfyStudioChatContentScript.test.ts`，含模型下拉：填充、切换、
被拒时回滚、一轮在飞时禁用；以及审核卡与计划清单卡：画清单、点头/要改、进度打勾）。
