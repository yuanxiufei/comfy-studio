#!/usr/bin/env node
/**
 * 把本仓的 ComfyUI/ 注册成 Comfy-Desktop 认得的一个「已有安装」，免去手点 UI。
 *
 * 为什么是这条路径（事实，来自上游源码，不是猜的）：
 *
 *   - Comfy-Desktop 的安装列表落在 `<userData>/installations.json`
 *     （Comfy-Desktop/src/main/installations.ts: dataPath = path.join(dataDir(), 'installations.json')）。
 *     Windows 上 dataDir() = Electron 的 userData = %APPDATA%\<package.json 的 name>，
 *     而 name 是 `comfyui-desktop-2`（上游 e2e/support/electronHarness.ts 也用这个常量）。
 *   - 它的 `git` 来源插件（Comfy-Desktop/src/main/sources/git.ts）恰好就是为
 *     「git 检出的 ComfyUI + 目录里的 venv」准备的：探到 .git 就按 git 类型建记录，
 *     启动命令是 `<venvPath>/Scripts/python.exe -s main.py <launchArgs>`，
 *     cwd 取 main.py 所在目录（根目录或 ComfyUI/ 子目录都支持）。
 *     也就是说不改上游一行，本仓 ComfyUI/ 就能被它直接拉起。
 *   - 首启流程看的是「列表里有没有 cloud/desktop 之外的安装」
 *     （Comfy-Desktop/src/main/lib/firstUseDetection.ts: skipPick），
 *     所以预置这一条后不再弹首次使用向导。
 *
 * 这个脚本只碰「用户数据目录」和本仓 setup/ 自己的东西，两个上游仓库零改动。
 */
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.dirname(here)
const comfyDir = path.join(repoRoot, 'ComfyUI')
const venvDir = path.join(comfyDir, '.venv')

/** Comfy-Desktop 的 Electron userData 目录（对齐上游 src/main/lib/paths.ts 的非 Linux 分支）。 */
function desktopUserDataDir() {
  if (process.platform === 'win32') {
    const appData = process.env.APPDATA ?? path.join(os.homedir(), 'AppData', 'Roaming')
    return path.join(appData, 'comfyui-desktop-2')
  }
  if (process.platform === 'darwin') {
    return path.join(os.homedir(), 'Library', 'Application Support', 'comfyui-desktop-2')
  }
  const xdg = process.env.XDG_CONFIG_HOME ?? path.join(os.homedir(), '.config')
  return path.join(xdg, 'comfyui-desktop-2')
}

function fail(message, hint) {
  console.error(`\n[X] ${message}`)
  if (hint) console.error(`    -> ${hint}`)
  process.exit(1)
}

function git(args, cwd) {
  try {
    return execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim()
  } catch {
    return ''
  }
}

function readJsonIfExists(file) {
  try {
    const raw = fs.readFileSync(file, 'utf8')
    const parsed = JSON.parse(raw)
    return parsed
  } catch {
    return null
  }
}

// ---- 前置检查：上游在位 + 引擎 venv 已装好 ----
if (!fs.existsSync(path.join(comfyDir, 'main.py'))) {
  fail(`没找到引擎入口：${path.join(comfyDir, 'main.py')}`)
}
const venvPython = path.join(
  venvDir,
  process.platform === 'win32' ? path.join('Scripts', 'python.exe') : path.join('bin', 'python')
)
if (!fs.existsSync(venvPython)) {
  fail(
    `引擎 venv 还没建好：${venvPython}`,
    process.platform === 'win32'
      ? '先跑：powershell -ExecutionPolicy Bypass -File setup/install-engine.ps1'
      : '先跑：pwsh setup/install-engine.ps1'
  )
}
if (!fs.existsSync(path.join(comfyDir, '.git'))) {
  fail(`ComfyUI 不是 git 检出：${comfyDir}`)
}

// ---- 组装记录（字段名对齐上游 git source 的 buildInstallation + probeInstallation）----
const branch = git(['rev-parse', '--abbrev-ref', 'HEAD'], comfyDir) || 'master'
const commit = git(['rev-parse', 'HEAD'], comfyDir) || ''
const repo = git(['config', '--get', 'remote.origin.url'], comfyDir) || 'https://github.com/Comfy-Org/ComfyUI.git'

const record = {
  id: 'inst-comfyui-local',
  name: 'ComfyUI (本仓)',
  createdAt: new Date().toISOString(),
  installPath: comfyDir,
  sourceId: 'git',
  status: 'installed',
  seen: true,
  repo,
  branch,
  commit,
  commitMessage: commit ? `${commit.slice(0, 8)} (本仓检出)` : '',
  venvPath: venvDir,
  venvName: path.basename(venvDir),
  launchArgs: '',
  launchMode: 'window',
  browserPartition: 'shared'
}

const userDataDir = desktopUserDataDir()
fs.mkdirSync(userDataDir, { recursive: true })

const installationsFile = path.join(userDataDir, 'installations.json')
const existing = readJsonIfExists(installationsFile)
const records = Array.isArray(existing) ? existing : []
const idx = records.findIndex((r) => r && (r.id === record.id || r.installPath === record.installPath))
if (idx >= 0) records[idx] = { ...records[idx], ...record }
else records.push(record)
fs.writeFileSync(installationsFile, JSON.stringify(records, null, 2))

// ---- settings.json：标记首启已完成（合并，不覆盖用户已有设置）----
const settingsFile = path.join(userDataDir, 'settings.json')
const settings = readJsonIfExists(settingsFile)
const merged = settings && typeof settings === 'object' && !Array.isArray(settings) ? settings : {}
merged.firstUseCompleted = true
if (typeof merged.telemetryEnabled !== 'boolean') merged.telemetryEnabled = false
fs.writeFileSync(settingsFile, JSON.stringify(merged, null, 2))

console.log(`\n[OK] 已注册安装：${record.name}`)
console.log(`     installPath : ${record.installPath}`)
console.log(`     venvPath    : ${record.venvPath}`)
console.log(`     git         : ${record.repo} (${branch} @ ${commit.slice(0, 8)})`)
console.log(`     写入        : ${installationsFile}`)
console.log(`     写入        : ${settingsFile}  (firstUseCompleted=true)`)
console.log('\n     下一步起壳：npm run dev\n')
