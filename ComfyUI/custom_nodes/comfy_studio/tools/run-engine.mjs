#!/usr/bin/env node
/**
 * 单独起引擎（不经桌面壳），用来验证后端本身没问题。
 * 参数原样透传给 ComfyUI/main.py，例如：
 *   npm run engine -- --port 8188
 *   npm run engine:help
 */
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

// 本脚本住在引擎侧自己人代码里（custom_nodes/comfy_studio/tools/），逐级往上推：
// tools -> comfy_studio -> custom_nodes -> ComfyUI
const here = path.dirname(fileURLToPath(import.meta.url))
const packageDir = path.resolve(here, '..')
const customNodesDir = path.resolve(packageDir, '..')
const comfyDir = path.resolve(customNodesDir, '..')
const isWin = process.platform === 'win32'
const venvPython = path.join(comfyDir, '.venv', isWin ? 'Scripts/python.exe' : 'bin/python')

if (!fs.existsSync(path.join(comfyDir, 'main.py'))) {
  console.error(`[X] 找不到引擎入口：${path.join(comfyDir, 'main.py')}`)
  process.exit(1)
}
if (!fs.existsSync(venvPython)) {
  console.error(`[X] 引擎 venv 还没建好：${venvPython}`)
  console.error('    -> 先跑 npm run setup')
  process.exit(1)
}

const passthrough = process.argv.slice(2)
const args = passthrough.length > 0 ? passthrough : ['--listen', '127.0.0.1', '--port', '8188']

const child = spawn(venvPython, ['-s', 'main.py', ...args], { cwd: comfyDir, stdio: 'inherit' })
child.on('exit', (code, signal) => process.exit(signal ? 1 : (code ?? 0)))
for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, () => child.kill(sig))
}
