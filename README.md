# comfy-studio

把两个上游项目就地打通成一个能用的工作台：

| 角色 | 上游仓库 | 在本仓的位置 | comfy-studio 加的代码 |
| --- | --- | --- | --- |
| 后端 · 引擎 | [Comfy-Org/ComfyUI](https://github.com/Comfy-Org/ComfyUI) | `ComfyUI/` | `custom_nodes/comfy_studio/`（skills / mcp / agent / HTTP 路由） |
| 前端 · 桌面壳 | [Comfy-Org/Comfy-Desktop](https://github.com/Comfy-Org/Comfy-Desktop) | `Comfy-Desktop/` | `lib/comfy_studio/`（MCP 宿主 / agent）+ 主进程 spawn·IPC·面板注入接线 |

两个上游仓库各自带 `.git`，被父仓库整目录忽略，就地保持原样；两边新增的都是它们各自的**标准扩展位**
（ComfyUI 认 `custom_nodes/`，桌面壳的 `lib/` 是它既有的 Python 脚本目录，会被打进 `extraResources`）。
除此之外的打通胶水收在 `setup/` 里。

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
npm run doctor         # 三段式体检：引擎 / 桌面壳 / 接线，逐项通过或给出下一步命令
npm run engine         # 不经桌面壳单独起引擎（默认 127.0.0.1:8188）
npm run mcp            # 单独起引擎侧 MCP server（stdio），喂给外部 agent 客户端
npm run studio         # 单独起桌面侧 comfy-studio 宿主（MCP 客户端 + skill 目录 + 对话 agent）
```

## comfy-studio 三件能力

agent / skill / mcp 三件能力**前后端各有一份**，按各自项目里的标准位置放：

### 后端（`ComfyUI/custom_nodes/comfy_studio/`）

* `skills/` —— skill = 参数化的工作流模板（`skills/workflows/*.json`）+ 严格参数校验
  （`params.py`）+ 执行器（`runner.py`：注入参数 → 入队 → 等完成 → 收图片）。
* `mcp/` —— 把引擎能力开成 MCP server：7 个通用工具（模型列表 / 提交工作流 / 队列 /
  历史 / 中断 / 列 skill / 跑 skill）外加每个 skill 一把 `skill__<id>`。
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

对话要模型，配在环境变量里（不落盘、不进仓库）：`COMFY_STUDIO_LLM_MODEL`（必填）、
`COMFY_STUDIO_LLM_BASE_URL`、`COMFY_STUDIO_LLM_API_KEY`。没配的话 `agent/config` 会明确
告诉你缺什么，`agent/chat` 直接报错，不会假装能聊。

桌面壳里的入口：画布侧栏多一个 comfy-studio 按钮，点开是对话抽屉
（`Comfy-Desktop/src/main/lib/comfyStudioChatContentScript.ts`），
它经 preload 桥 `window.__comfyDesktop2.ComfyStudio` 走 IPC 找主进程，
主进程再按需 spawn 上面的宿主进程。

## 打通是怎么做到的

除了上面新增的扩展位，胶水本身靠的是 Comfy-Desktop 自己就支持「接管已有的 git 检出 + 目录里的 venv」这个能力：

1. **引擎侧**：`setup/install-engine.ps1` 在 `ComfyUI/.venv` 建 Python 3.11 环境，装 CUDA 版 torch（本机有 N 卡时；否则回退 CPU 轮子）和上游 `requirements.txt` 的其余依赖。
2. **接线侧**：`setup/seed-desktop.mjs` 往 Comfy-Desktop 的安装清单
   （Windows：`%APPDATA%\comfyui-desktop-2\installations.json`）写一条 `sourceId: "git"` 的记录，指向本仓 `ComfyUI/` 与它的 `.venv`。
   Comfy-Desktop 的 git 来源插件识别到目录里的 `.git` 就按 git 型安装处理，
   启动命令是 `<venvPath>/Scripts/python.exe -s main.py <launchArgs>`，cwd 取 `main.py` 所在目录。
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

## 目录

```
comfy-studio/
├─ ComfyUI/          # 上游引擎（父仓库忽略）
│  └─ custom_nodes/comfy_studio/   # 后端三件：skills / mcp / agent + routes
├─ Comfy-Desktop/    # 上游桌面壳（父仓库忽略）
│  └─ lib/comfy_studio/            # 前端三件：mcp（宿主）/ skills / agent + 宿主进程接口
│     └─ tests/                    # 宿主端到端测试（真进程 + 真 MCP 子进程）
├─ setup/            # 打通物料：装环境 / 注册安装 / 体检 / 单独起引擎(engine) / mcp / studio
├─ reference/        # 上游参考仓库搬运池（父仓库忽略，后期整体可删）
└─ .cache/           # 脚本产出的过滤清单、自检输出、安装日志（父仓库忽略）
```

桌面侧宿主的行为验证（需要同一仓库的 ComfyUI 检出与它的 venv，缺了整组跳过）：

```powershell
cd Comfy-Desktop/lib
..\..\ComfyUI\.venv\Scripts\python.exe -m unittest comfy_studio.tests.test_host_e2e -v
```

它用本地假模型服务顶替真 LLM：第一轮让模型要一次 `comfy_list_skills`，第二轮给结论，
以此确认「agent 真的经 MCP 工具拿了引擎的数据」，全程不联网。桌面壳自己的
TypeScript 侧测试走 `pnpm test`（新增面板脚本的用例在
`src/main/lib/comfyStudioChatContentScript.test.ts`）。
