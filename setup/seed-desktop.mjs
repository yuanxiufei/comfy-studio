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
 *     「git 检出的 ComfyUI + 目录里的 venv」准备的：启动命令是
 *     `<venvPath>/Scripts/python.exe -s main.py <launchArgs>`，
 *     cwd 取 main.py 所在目录（根目录或 ComfyUI/ 子目录都支持）。
 *     这条命令只用到 venvPath 与 main.py，不读 .git —— 所以本仓 ComfyUI/ 现在虽然已经
 *     整份收进父仓库、自己没有 .git，照样能被它直接拉起，不改上游一行。
 *     （`.git` 只被 probeInstallation 用，那是 UI 里"添加已有安装"才走的路径；本脚本直接
 *     写记录、不经过它。代价：详情页里依赖 .git 的动作，比如 git pull，对这个安装不可用。）
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
/** 已入库形态下上游身份的唯一出处：studio/upstream.json 里 ComfyUI 那一侧的基线记录。 */
function upstreamBaseline() {
  const manifest = readJsonIfExists(path.join(repoRoot, 'studio', 'upstream.json'))
  const side = Array.isArray(manifest?.sides)
    ? manifest.sides.find((s) => s && s.checkout === 'ComfyUI')
    : null
  if (!side?.baselineCommit) {
    fail(
      `ComfyUI 没有 .git、studio/upstream.json 里也没记基线：认不出这是哪份上游`,
      '在 studio/upstream.json 的 ComfyUI 那一侧补齐 baselineCommit / baselineBranch / upstream'
    )
  }
  return {
    commit: side.baselineCommit,
    branch: side.baselineBranch ?? '',
    repo: side.upstream ?? '',
    subject: side.baselineSubject ?? '',
    version: side.upstreamVersion ?? ''
  }
}

// ---- 组装记录（字段名对齐上游 git source 的 buildInstallation + probeInstallation）----
// 上游形态：独立检出（有 .git）能从 git 读身份；已入库（无 .git，内容由父仓跟踪）只能读清单。
// 注意：没有 .git 时绝不能在这两个目录里跑 git —— 它会一路往上落到父仓，把父仓的 HEAD
// 当成本仓 ComfyUI 的 HEAD 写进记录里。
const embedded = !fs.existsSync(path.join(comfyDir, '.git'))
const baseline = embedded ? upstreamBaseline() : null

const branch = embedded ? baseline.branch : git(['rev-parse', '--abbrev-ref', 'HEAD'], comfyDir) || 'master'
const commit = embedded ? baseline.commit : git(['rev-parse', 'HEAD'], comfyDir) || ''
const repo = embedded
  ? baseline.repo
  : git(['config', '--get', 'remote.origin.url'], comfyDir) || 'https://github.com/Comfy-Org/ComfyUI.git'
const commitMessage = embedded
  ? `${commit.slice(0, 8)} 上游基线${baseline.version ? ` ${baseline.version}` : ''}${baseline.subject ? `：${baseline.subject}` : ''}（已入库）`
  : `${commit.slice(0, 8)} (本仓检出)`

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
  commitMessage,

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
console.log(
  `     git         : ${record.repo} (${branch || '未记分支'} @ ${commit.slice(0, 8)})` +
    `${embedded ? '  [已入库，无独立 .git]' : ''}`
)
console.log(`     写入        : ${installationsFile}`)
console.log(`     写入        : ${settingsFile}  (firstUseCompleted=true)`)
if (embedded) {
  console.log('\n     注意        : ComfyUI 已整份收进父仓库（自己没有 .git）：起壳与跑引擎都不受影响，')
  console.log('                   但桌面详情页里依赖 .git 的动作（git pull 之类）对这个安装不可用。')
  console.log('                   要更新上游：另行 clone 上游到临时目录，把内容搬回来，再改 studio/upstream.json 的基线。')
}
console.log('\n     下一步起壳：npm run dev\n')
