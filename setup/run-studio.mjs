#!/usr/bin/env node
/**
 * 单独起桌面侧的 comfy-studio 宿主（MCP 客户端 + skill 目录 + 对话 agent）。
 *
 * 桌面壳自己会按需拉起它（Electron 主进程 spawn，见 Comfy-Desktop 的
 * `src/main/lib/comfyStudioHost.ts`）；这个脚本是给人手动排查用的，
 * 行为与桌面壳拉起的那条完全一致：同样用引擎 venv 的 python，
 * 同样以 `Comfy-Desktop/lib` 为 cwd。
 *
 * 用法：
 *   node setup/run-studio.mjs            # 交互式：从 stdin 读行分隔 JSON-RPC
 *   node setup/run-studio.mjs --help     # 看宿主自己的全部参数
 *
 * 对话要模型，模型配在环境变量里（不落盘、不进仓库）：
 *   COMFY_STUDIO_LLM_MODEL     必填，例如 qwen2.5:7b
 *   COMFY_STUDIO_LLM_BASE_URL  可选，默认 https://api.openai.com/v1
 *   COMFY_STUDIO_LLM_API_KEY   可选，本地服务通常不需要
 */
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.dirname(here)
const comfyDir = path.join(repoRoot, 'ComfyUI')
const libDir = path.join(repoRoot, 'Comfy-Desktop', 'lib')
const packageDir = path.join(libDir, 'comfy_studio')
const isWin = process.platform === 'win32'
const venvPython = path.join(comfyDir, '.venv', isWin ? 'Scripts/python.exe' : 'bin/python')

if (!fs.existsSync(path.join(packageDir, '__main__.py'))) {
  console.error(`[X] 找不到桌面侧 comfy_studio 包：${packageDir}`)
  process.exit(1)
}
if (!fs.existsSync(venvPython)) {
  console.error(`[X] 引擎 venv 还没建好：${venvPython}`)
  console.error('    -> 先跑 npm run setup')
  process.exit(1)
}

const passthrough = process.argv.slice(2)
const child = spawn(
  venvPython,
  ['-X', 'utf8', '-m', 'comfy_studio', '--comfyui-dir', comfyDir, ...passthrough],
  {
    // cwd 必须是包父目录，`-m comfy_studio` 才找得到包。
    cwd: libDir,
    stdio: 'inherit'
  }
)
child.on('exit', (code, signal) => process.exit(signal ? 1 : (code ?? 0)))
for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, () => child.kill(sig))
}
