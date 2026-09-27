#!/usr/bin/env node
/**
 * 单独起引擎侧的 MCP server（行分隔 JSON-RPC 2.0 over stdio）。
 *
 * 用途：把 ComfyUI 的能力（模型列表 / 入队 / 队列 / 历史 / 中断 / 跑 skill）
 * 交给外部 agent 客户端。给它一个绝对路径就行，例如某客户端的 MCP 配置：
 *
 *   {
 *     "mcpServers": {
 *       "comfy-studio": {
 *         "command": "node",
 *         "args": ["<仓库根>/ComfyUI/custom_nodes/comfy_studio/tools/run-mcp.mjs"]
 *       }
 *     }
 *   }
 *
 * 注意：**stdout 是协议通道**，本脚本与子进程的所有诊断都走 stderr，
 * 别在 stdout 上打任何东西，否则会污染 JSON 流。
 * 参数原样透传给 `python -m comfy_studio.mcp`（例如 --skills-dir）。
 */
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

// 本脚本住在引擎侧自己人代码里（custom_nodes/comfy_studio/tools/）：包目录就是自己的上一层，
// cwd 必须是 custom_nodes（`-m comfy_studio.mcp` 才找得到包），再上一层才是 ComfyUI。
const here = path.dirname(fileURLToPath(import.meta.url))
const packageDir = path.resolve(here, '..')
const customNodes = path.resolve(packageDir, '..')
const comfyDir = path.resolve(customNodes, '..')
const isWin = process.platform === 'win32'
const venvPython = path.join(comfyDir, '.venv', isWin ? 'Scripts/python.exe' : 'bin/python')

if (!fs.existsSync(path.join(packageDir, 'mcp', 'server.py'))) {
  console.error(`[X] 找不到引擎侧 comfy_studio 包：${packageDir}`)
  process.exit(1)
}
if (!fs.existsSync(venvPython)) {
  console.error(`[X] 引擎 venv 还没建好：${venvPython}`)
  console.error('    -> 先跑 npm run setup')
  process.exit(1)
}

const passthrough = process.argv.slice(2)
const child = spawn(venvPython, ['-s', '-m', 'comfy_studio.mcp', ...passthrough], {
  // cwd 必须是 custom_nodes，`-m comfy_studio.mcp` 才找得到包。
  cwd: customNodes,
  stdio: 'inherit'
})
child.on('exit', (code, signal) => process.exit(signal ? 1 : (code ?? 0)))
for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, () => child.kill(sig))
}
