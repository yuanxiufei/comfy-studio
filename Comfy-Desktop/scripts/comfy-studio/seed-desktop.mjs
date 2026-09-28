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
 * 这个脚本碰两处：一是用户数据目录（installations.json / settings.json），二是被
 * ComfyUI/.gitignore 忽略的 ComfyUI/extra_model_paths.yaml（共享池接线，机器本地件，只在它
 * 不存在时生成）。两份上游检出里被父仓库跟踪的内容一律不动——读引擎树里那份自述只为认身份。
 */
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

// 本脚本住在桌面壳自己的脚本区（scripts/comfy-studio/），逐级往上推：
// comfy-studio -> scripts -> Comfy-Desktop -> 仓库根
const here = path.dirname(fileURLToPath(import.meta.url))
const scriptsDir = path.resolve(here, '..')
const desktopDir = path.resolve(scriptsDir, '..')
const repoRoot = path.resolve(desktopDir, '..')
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
    return execFileSync('git', args, {
      cwd,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore']
    }).trim()
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
    '先跑 npm run setup（引擎包里 tools/install-engine.ps1）'
  )
}
/**
 * 已入库形态下上游身份的唯一出处：引擎树自己带的那份自述
 * （ComfyUI/custom_nodes/comfy_studio/upstream-baseline.json，跟引擎代码同处一地）。
 */
function upstreamBaseline() {
  const file = path.join(comfyDir, 'custom_nodes', 'comfy_studio', 'upstream-baseline.json')
  if (!fs.existsSync(file)) {
    return fail(
      `认不出这是哪份上游：缺 ${file}`,
      'ComfyUI/ 整份收在父仓里、自己没有 .git，身份只能从这份自述读；补上它（字段见 README 的「上游账本」）'
    )
  }
  let desc
  try {
    desc = JSON.parse(fs.readFileSync(file, 'utf8'))
  } catch (err) {
    return fail(`读不了 ${file}：${err.message}`)
  }
  for (const key of ['repo', 'commit', 'branch']) {
    if (!desc[key])
      return fail(`${file} 没记 ${key}：认不出压在哪份上游上`, '升级上游时同步改这份自述')
  }
  return {
    commit: desc.commit,
    branch: desc.branch,
    repo: desc.repo,
    subject: desc.subject ?? '',
    version: desc.version ?? ''
  }
}

// ---- 组装记录（字段名对齐上游 git source 的 buildInstallation + probeInstallation）----
// 上游形态：独立检出（有 .git）能从 git 读身份；已入库（无 .git，内容由父仓跟踪）只能读清单。
// 注意：没有 .git 时绝不能在这两个目录里跑 git —— 它会一路往上落到父仓，把父仓的 HEAD
// 当成本仓 ComfyUI 的 HEAD 写进记录里。
const embedded = !fs.existsSync(path.join(comfyDir, '.git'))
const baseline = embedded ? upstreamBaseline() : null

const branch = embedded
  ? baseline.branch
  : git(['rev-parse', '--abbrev-ref', 'HEAD'], comfyDir) || 'master'
const commit = embedded ? baseline.commit : git(['rev-parse', 'HEAD'], comfyDir) || ''
const repo = embedded
  ? baseline.repo
  : git(['config', '--get', 'remote.origin.url'], comfyDir) ||
    'https://github.com/Comfy-Org/ComfyUI.git'
const commitMessage = embedded
  ? `${commit.slice(0, 8)} 上游基线${baseline.version ? ` ${baseline.version}` : ''}${baseline.subject ? `：${baseline.subject}` : ''}（已入库）`
  : `${commit.slice(0, 8)} (本仓检出)`

// installPath 是**本仓根目录**，不是 ComfyUI/ 本身。桌面壳认的是「安装根下套一个
// ComfyUI/ 子目录、venv 在 ComfyUI/.venv」这套布局（上游 git source 的 clone 结果就这样）：
//   - 起引擎：sources/git.ts 的 getLaunchCommand = resolveVenvPython(venvPath) + findMainPy(installPath)，
//     而 findMainPy 先试 <installPath>/main.py、再试 <installPath>/ComfyUI/main.py（两种布局都收）；
//   - 起宿主：lib/comfyStudioHost.ts 的 resolveStudioCommand 走 lib/pythonEnv.ts 的
//     getActivePythonPath → getVenvPythonPath(installPath) = <installPath>/ComfyUI/.venv/Scripts/python.exe，
//     **这条只看 installPath，完全不读 venvPath 字段**。
// 所以 installPath 写偏一个层级时，引擎还能起（那条读 venvPath），但面板一开口就报
// "这个安装没有可用的 venv python 或 ComfyUI 检出"。
const record = {
  id: 'inst-comfyui-local',
  name: 'ComfyUI (本仓)',
  createdAt: new Date().toISOString(),
  installPath: repoRoot,
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
const idx = records.findIndex(
  (r) => r && (r.id === record.id || r.installPath === record.installPath)
)
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

// ---- ComfyUI/extra_model_paths.yaml：把「共享池接线」从手写孤本变成可复现的一步 ----
// 依据（核过源码）：ComfyUI/main.py 的 apply_custom_paths() 读 <ComfyUI>/extra_model_paths.yaml；
// 而桌面壳注入的 instance-model-paths/<安装id>.yaml 只有模型目录、没有 custom_nodes 键，
// 所以共享插件池（漫剧工作流用的 H3 那几包只住在池里）只能靠这份文件。它被 ComfyUI/.gitignore
// 忽略，于是换台机器时唯一会静默丢掉的正是它——这里按现成的探测手段把它补出来。
//
// 池根从哪来（不写死机器路径）：
//   1) COMFYUI_SHARED_ROOT 显式指定，优先；
//   2) 桌面壳自己的 settings.json 里 modelsDirs 的上一级——那是它自己记的共享模型目录，
//      池根就是它的父目录（models 与 custom_nodes 同级）。
// 两个都拿不到就不生成，并把缺什么说清楚（不静默）。
const sharedYaml = path.join(comfyDir, 'extra_model_paths.yaml')
const declaredDirs = merged.modelsDirs
const modelsDirs =
  typeof declaredDirs === 'string'
    ? declaredDirs
    : Array.isArray(declaredDirs)
      ? (declaredDirs.find((v) => typeof v === 'string' && v.trim() !== '') ?? '')
      : ''
const poolRoot = process.env.COMFYUI_SHARED_ROOT || (modelsDirs ? path.dirname(modelsDirs) : '')
if (!poolRoot) {
  console.log(
    '\n     共享池接线  : 未接（settings.json 里没有 modelsDirs，也没给 COMFYUI_SHARED_ROOT）'
  )
  console.log('                   H3 等节点包只住在共享池里，没接上时那些工作流会整片红节点。')
  console.log(
    '                   接法：壳里指定一个共享目录，或 COMFYUI_SHARED_ROOT=<池根> npm run seed'
  )
} else if (fs.existsSync(sharedYaml)) {
  // 已有接线（很可能是手写并带注释的那份）：一个字都不改，只核对它引用的池根是不是这次推导出的
  const wired = fs.readFileSync(sharedYaml, 'utf8').includes(poolRoot)
  console.log(`\n     共享池接线  : 已在位，未改动  ${sharedYaml}`)
  if (!wired) {
    console.log(`     !!          : 它里面没出现这次推导出的池根 ${poolRoot}`)
    console.log(
      '                   跑 npm run doctor 看详情；要按当前推导重生成，先删掉它再跑 seed。'
    )
  }
} else {
  const modelsDir = path.join(poolRoot, 'models')
  const nodesDir = path.join(poolRoot, 'custom_nodes')
  const typeDirs = fs.existsSync(modelsDir)
    ? fs
        .readdirSync(modelsDir, { withFileTypes: true })
        .filter((e) => e.isDirectory())
        .map((e) => e.name)
        .sort()
    : []
  const nodesOk = fs.existsSync(nodesDir)
  if (typeDirs.length === 0 && !nodesOk) {
    console.log(
      `\n     共享池接线  : 未生成 —— 推导出的池根下既没有 models\\ 也没有 custom_nodes\\`
    )
    console.log(`                   ${poolRoot}`)
    console.log(
      '                   核对 COMFYUI_SHARED_ROOT / settings.json 的 modelsDirs 是不是这个池。'
    )
  } else {
    const lines = [
      '# 由 npm run seed 生成；本文件被 ComfyUI/.gitignore 忽略（只对本机生效，不进版本库）。',
      '#',
      '# 为什么需要它（核过源码，不是推测）：',
      '#   ComfyUI/main.py 的 apply_custom_paths() 会读 <ComfyUI>/extra_model_paths.yaml（140-148 行），',
      '#   而桌面壳注入的 instance-model-paths/<安装id>.yaml 只含模型目录、不含 custom_nodes，',
      '#   所以共享插件池这一半只能写在这里；两份同时生效（同一路径只做 is_default 提升，不重复追加）。',
      '#',
      `# 池根来自 ${process.env.COMFYUI_SHARED_ROOT ? '环境变量 COMFYUI_SHARED_ROOT' : 'settings.json 的 modelsDirs 的上一级'}：${poolRoot}`,
      '# 模型类型清单按池里 models\\ 实际子目录枚举，不另存一份会漂的清单。',
      '',
      'shared_models:',
      `  base_path: '${modelsDir}'`,
      '  is_default: true',
      ...typeDirs.map((n) => `  '${n}': '${n}/'`),
      '',
      '# 插件池与模型池同级（<池根>\\custom_nodes），不蹭上面的 base_path，单开一节写绝对路径。',
      'shared_custom_nodes:',
      `  'custom_nodes': '${nodesDir}'`,
      ''
    ]
    fs.writeFileSync(sharedYaml, lines.join('\n'))
    console.log(`\n     共享池接线  : 已生成  ${sharedYaml}`)
    console.log(
      `                   ${typeDirs.length} 个模型类型 + 插件池 ${nodesDir}` +
        `${nodesOk ? '' : '（这个目录不存在，核对一下）'}`
    )
  }
}

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
  console.log(
    '\n     注意        : ComfyUI 已整份收进父仓库（自己没有 .git）：起壳与跑引擎都不受影响，'
  )
  console.log(
    '                   但桌面详情页里依赖 .git 的动作（git pull 之类）对这个安装不可用。'
  )
  console.log(
    '                   要更新上游：另行 clone 上游到临时目录，把内容搬回来，再改引擎树里那份'
  )
  console.log('                   custom_nodes/comfy_studio/upstream-baseline.json 的基线。')
}
console.log('\n     下一步起壳：npm run dev\n')
