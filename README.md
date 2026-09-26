# Comfy Studio

ComfyUI 生态的桌面工作台：**画布模式 + Agent/Skill 模式**，共享同一个本地 ComfyUI 后端。

```
┌─ 桌面壳 apps/desktop (Electron)
│   ├─ 主窗口：直接加载 ComfyUI 自带的画布前端（http://127.0.0.1:8188）
│   └─ Skill 面板：参数化表单运行 skill，实时进度 + 结果预览
├─ packages/comfy-sdk      本地 ComfyUI 的 HTTP + WebSocket 客户端
├─ packages/comfy-skills   skill = 参数化工作流模板（加载/校验/运行）
├─ packages/comfy-mcp      把本地 ComfyUI 暴露为 MCP 工具（stdio，供 Claude/Cursor 等 Agent 调用）
└─ 后端：本机已有的 ComfyUI（默认 http://127.0.0.1:8188）
```

## 与上游生态的对应关系

| 本项目模块 | 对应官方仓库 | 取法 |
|---|---|---|
| ComfyUI 后端 | Comfy-Org/ComfyUI | 直接连接/拉起本机实例，不复制代码 |
| 画布主窗口 | Comfy-Org/ComfyUI_frontend | 用 ComfyUI 内置前端，不重复造 |
| 桌面壳 | Comfy-Org/Comfy-Desktop | 只做最小壳：拉起后端 + 窗口管理 |
| comfy-sdk | comfy-python-sdk / typescript-sdk | 自实现薄客户端，无外部依赖 |
| comfy-mcp | Comfy-Org/comfy-mcp | 自实现（stdio JSON-RPC，无 SDK 依赖），工具集对齐 |
| comfy-skills | Comfy-Org/comfy-skills | 借鉴其"skill = 工作流 + 参数"模式，执行层全本地 |
| 节点模板 | workflow_templates | 逐个做成参数化 skill（见 skills/*.json） |

## 准备

1. Node.js >= 18.17
2. 本机已能运行 ComfyUI（`python main.py`）

## 使用

```powershell
npm install          # 首次安装依赖
npm run build         # 编译全部 workspace
npm run app           # 启动桌面应用
```

首次启动会在用户数据目录生成 `config.json`：

```json
{
  "comfyUrl": "http://127.0.0.1:8188",
  "comfyuiDir": null,
  "pythonCmd": "python"
}
```

- ComfyUI 已在跑：直接连接 `comfyUrl`。
- 没在跑：把 `comfyuiDir` 填成本地仓库路径（如 `D:/code/voide/ComfyUI`），桌面端会用 `pythonCmd` 拉起 `main.py --port 8188` 并等待就绪。

### Skill 面板

菜单「查看 → Skill 面板」：选 skill → 填参数（表单按 skill 的 params 定义生成）→ 运行，进度和结果图直接展示。

### MCP（给外部 Agent 用）

```powershell
npm run mcp   # 等价于 node packages/comfy-mcp/dist/index.js
```

在 Claude Code / Cursor 等客户端注册 stdio MCP server：

```json
{
  "mcpServers": {
    "comfy-studio": {
      "command": "node",
      "args": ["D:/code/voide/comfy-studio/packages/comfy-mcp/dist/index.js"],
      "env": {
        "COMFY_URL": "http://127.0.0.1:8188",
        "COMFY_SKILLS_DIR": "D:/code/voide/comfy-studio/packages/comfy-skills/skills"
      }
    }
  }
}
```

工具一览：

| 工具 | 作用 |
|---|---|
| `comfy_list_models` | 列出本机模型（checkpoints / loras / vae / …） |
| `comfy_list_skills` | 列出 skill 及参数定义 |
| `comfy_run_skill` | 运行 skill 并等待完成，返回输出文件 |
| `skill__<id>` | 每个 skill 额外暴露为一把独立工具（带参数 schema） |
| `comfy_submit_workflow` | 直接提交 API 格式工作流（不等待） |
| `comfy_get_history` / `comfy_get_queue` / `comfy_interrupt` | 查询/控制执行 |

## 编写一个 skill

`packages/comfy-skills/skills/` 下加一个 JSON：

```json
{
  "id": "my-skill",
  "title": "我的技能",
  "description": "给 Agent 看的能力描述，写清楚什么时候该用它",
  "workflow": {
    "3": { "class_type": "KSampler", "inputs": { "...": "ComfyUI API 格式的节点图" } }
  },
  "params": [
    { "name": "positive", "type": "string", "required": true, "node": "6", "field": "text" }
  ]
}
```

- `workflow`：ComfyUI API 格式（画布里「导出（API）」得到的就是它）
- `params[].node/field`：参数值注入到哪个节点的哪个输入
- 约定：名为 `seed` 的参数传 `-1` 表示每次随机
- 加载时严格校验（节点存在、字段存在、类型合法、无重名），错误直接抛出

## 路线图

- [ ] P2：应用内聊天 Agent（LLM 选 skill / 生成工作流，画布 ↔ skill 双向转换）
- [ ] P3：导入 ComfyUI 官方 workflow_templates 批量转 skill
- [ ] P4：内置 ComfyUI-Manager / comfy-complete 做节点集管理
