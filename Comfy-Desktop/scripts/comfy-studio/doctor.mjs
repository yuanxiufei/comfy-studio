#!/usr/bin/env node
/**
 * 打通体检：只读检查，不改任何东西。
 *
 * 按「自己人代码入库 -> 后端(引擎) -> 前端(桌面壳) -> 接线(安装记录)」四段逐项核对，
 * 每项给出 通过/失败 与失败时的下一步命令。任何一项失败都以非 0 退出，
 * 方便在 CI 或脚本里当门禁用。
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
const isWin = process.platform === 'win32'
const venvPython = path.join(comfyDir, '.venv', isWin ? 'Scripts/python.exe' : 'bin/python')

const results = []
function check(name, ok, detail = '', hint = '') {
  results.push({ name, ok, detail, hint })
  const mark = ok ? '\x1b[32m[OK]\x1b[0m' : '\x1b[31m[--]\x1b[0m'
  console.log(`${mark} ${name}${detail ? `  ${detail}` : ''}`)
  if (!ok && hint) console.log(`       -> ${hint}`)
}

function tryRun(file, args, opts = {}) {
  try {
    return { ok: true, out: execFileSync(file, args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], ...opts }).trim() }
  } catch (err) {
    return { ok: false, out: String(err?.message ?? err) }
  }
}

function desktopUserDataDir() {
  if (process.platform === 'win32') {
    return path.join(process.env.APPDATA ?? path.join(os.homedir(), 'AppData', 'Roaming'), 'comfyui-desktop-2')
  }
  if (process.platform === 'darwin') {
    return path.join(os.homedir(), 'Library', 'Application Support', 'comfyui-desktop-2')
  }
  return path.join(process.env.XDG_CONFIG_HOME ?? path.join(os.homedir(), '.config'), 'comfyui-desktop-2')
}

/** venv 的 site-packages：Windows 在 Lib/，POSIX 在 lib/pythonX.Y/。 */
function venvSitePackages() {
  const base = path.join(comfyDir, '.venv', isWin ? 'Lib' : 'lib')
  if (!fs.existsSync(base)) return null
  if (isWin) return path.join(base, 'site-packages')
  const py = fs.readdirSync(base).find((n) => n.startsWith('python'))
  return py ? path.join(base, py, 'site-packages') : null
}

// 自己人代码直接住在两份上游检出的扩展位里 —— 那就是唯一事实源，没有第三份副本；每侧的上游自述
// 也放在它自己的落点里（`<落点>/upstream-baseline.json`），人读的和脚本读的是同一份文件。
//   1) 落点目录里磁盘上有的文件，是否都被父仓跟踪。引擎侧落点正好在上游 .gitignore 的
//      /custom_nodes/ 里面：新增文件不进库时 git status 都看不见，所以只能机械核对；
//   2) 自述在不在、字段齐不齐 —— 引擎那份还是 npm run seed 认上游身份的唯一出处
//      （ComfyUI/ 整份收在父仓里，自己没有 .git 可以问）；
//   3) 接线补丁还在不在：applied 正常；absent 是换过上游内容、还没重放补丁；
//      conflict 说明上游把那几个文件改过了，要人工并回补丁（上游升级最容易卡在这）。
const SIDES = [
  { checkout: 'ComfyUI', selfDesc: 'custom_nodes/comfy_studio/upstream-baseline.json' },
  { checkout: 'Comfy-Desktop', selfDesc: 'lib/comfy_studio/upstream-baseline.json' }
]
const BASELINE_KEYS = ['repo', 'commit', 'branch']
const SKIP_DIRS = new Set(['__pycache__', '.pytest_cache', 'node_modules'])

/** 读一侧的上游自述：身份 + 落点目录，以及它自己带的补丁（有就给出绝对路径）。 */
function readSide(side) {
  const file = path.join(repoRoot, side.checkout, side.selfDesc)
  if (!fs.existsSync(file)) throw new Error(`缺 ${side.checkout} 的上游自述：${file}`)
  let desc
  try {
    desc = JSON.parse(fs.readFileSync(file, 'utf8'))
  } catch (err) {
    // 带上 cause：重抛时别把原始错误丢掉（上游 eslint 的 preserve-caught-error 就盯这个）
    throw new Error(`${file} 不是合法 JSON：${err.message}`, { cause: err })
  }
  const missing = BASELINE_KEYS.filter((k) => !desc[k])
  if (missing.length > 0) throw new Error(`${file} 缺字段：${missing.join('、')}`)
  // placement 可以是一个目录，也可以是一串：宿主侧自己人代码分两处 —— lib/comfy_studio 是宿主
  // 进程本体，scripts/comfy-studio 是胶水脚本（.mjs 必须落在桌面壳自己的 scripts 区，上游 eslint
  // 只给 ./scripts/** 的 js/mjs/cjs 配了 node 全局，塞进 lib/ 会被判成一片 no-undef）。
  const placements = Array.isArray(desc.placement) ? desc.placement : [desc.placement]
  if (placements.length === 0 || placements.some((p) => typeof p !== 'string' || p.trim() === '')) {
    throw new Error(`${file} 的 placement 无效：${JSON.stringify(desc.placement)}`)
  }
  return {
    desc,
    file,
    placementDirs: placements.map((p) => path.join(repoRoot, side.checkout, p)),
    patch: desc.patch ? path.join(path.dirname(file), desc.patch) : null
  }
}

/** 落点目录里磁盘上有的文件（相对仓库根），跳过 bytecode 与构建产物。 */
function filesUnder(dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const abs = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      if (!SKIP_DIRS.has(entry.name)) filesUnder(abs, out)
    } else if (entry.isFile() && !/\.(pyc|pyo)$/.test(entry.name)) {
      out.push(path.relative(repoRoot, abs).split(path.sep).join('/'))
    }
  }
  return out
}

console.log('\n== 自己人代码：入库状态 ==')
try {
  for (const side of SIDES) {
    const { desc, placementDirs, patch } = readSide(side)
    for (const dir of placementDirs) {
      if (!fs.existsSync(dir)) throw new Error(`自述记的落点不存在：${dir}`)
    }
    const files = placementDirs.flatMap((dir) => filesUnder(dir))
    const where = placementDirs.map((dir) => path.relative(repoRoot, dir).split(path.sep).join('/'))
    // 引擎侧落点在上游 .gitignore 的 /custom_nodes/ 里，所以必须显式点名路径问 git
    const ls = tryRun('git', ['ls-files', '-z', '--', ...where], { cwd: repoRoot })
    if (!ls.ok) throw new Error(`git ls-files 失败：${ls.out}`)
    const tracked = new Set(ls.out.split('\0').filter(Boolean))
    const untracked = files.filter((rel) => !tracked.has(rel))
    check(
      `${side.checkout} 落点文件已入库`,
      untracked.length === 0,
      untracked.length === 0
        ? `${where.join(' + ')} · ${files.length} 个文件 · 基线 ${desc.version ?? '-'} @ ${String(desc.commit).slice(0, 8)}`
        : `${untracked.length} 个没被父仓跟踪：${untracked.slice(0, 3).join('、')}${untracked.length > 3 ? ' …' : ''}`,
      '新增文件要逐个 git add -f：引擎侧落点在上游 .gitignore 的 /custom_nodes/ 里，普通 git add 加不上'
    )

    if (!patch) continue
    if (!fs.existsSync(patch)) {
      check(`${side.checkout} 接线补丁在位`, false, path.basename(patch), `自述的 patch 字段指着 ${patch}，但它不在`)
      continue
    }
    const cwd = path.join(repoRoot, side.checkout)
    const applied = tryRun('git', ['apply', '--check', '--reverse', patch], { cwd }).ok
    const clean = applied ? false : tryRun('git', ['apply', '--check', patch], { cwd }).ok
    const state = applied ? 'applied' : clean ? 'absent' : 'conflict'
    check(
      `${side.checkout} 接线补丁已打上`,
      state === 'applied',
      `${path.basename(patch)} ${state}`,
      state === 'conflict'
        ? `补丁既打不上也退不掉（上游改过那几个文件）：git -C ${side.checkout} diff -- <文件> 看清哪几处是我们的，再更新 ${path.relative(repoRoot, patch).split(path.sep).join('/')}`
        : `补丁还没打上：git -C ${side.checkout} apply "${patch}"`
    )
  }
} catch (err) {
  check(
    '自己人代码入库状态可核对',
    false,
    String(err?.message ?? err),
    '两侧自述分别在 ComfyUI/custom_nodes/comfy_studio/upstream-baseline.json 与 Comfy-Desktop/lib/comfy_studio/upstream-baseline.json'
  )
}

console.log('\n== 后端：ComfyUI 引擎 ==')
check('Node 版本 >= 22', Number(process.versions.node.split('.')[0]) >= 22, `v${process.versions.node}`)
check('ComfyUI 就位', fs.existsSync(path.join(comfyDir, 'main.py')), comfyDir, '上游仓库缺失')
check('引擎 venv 存在', fs.existsSync(venvPython), venvPython, '跑 npm run setup')

if (fs.existsSync(venvPython)) {
  // 注意：内联 Python 只用单引号，避免双引号在 Windows 的 argv 重组里被拆坏
  const probe = tryRun(venvPython, [
    '-c',
    'import torch,sys;gpu=torch.cuda.get_device_name(0) if torch.cuda.is_available() else \'-\';print(\'torch=%s cuda_build=%s cuda_ready=%s gpu=%s\'%(torch.__version__,torch.version.cuda,torch.cuda.is_available(),gpu))'
  ], { cwd: comfyDir })
  check('torch 可导入', probe.ok, probe.ok ? probe.out : probe.out.split('\n')[0], 'pip 装失败时看 .cache/engine-torch.log')
  if (probe.ok && probe.out.includes('cuda_ready=False')) {
    console.log('       !! torch 是 CPU 轮子：能跑但吃不到 GPU。要 GPU 重装：npm run setup（带 -TorchIndex cu130）')
  }
  const frontend = tryRun(venvPython, ['-c', 'import comfyui_frontend_package,os;print(os.path.dirname(comfyui_frontend_package.__file__))'], { cwd: comfyDir })
  check('画布前端包 comfyui_frontend_package 可导入', frontend.ok, frontend.ok ? '' : frontend.out.split('\n')[0], '依赖没装全，重跑 npm run setup')

  // 上游 requirements.txt 钉的 comfyui-workflow-templates 只是薄封装，模板数据在
  // core/json 里、缩略图在 6 个 media-* 包里（引擎包里 tools/install-engine.ps1 第 4 步用官方源装全）。
  // 数据缺了只是列表空，缩略图缺了是另一回事，且会留下长尾故障：
  //   /templates/<name>-1.webp 全 404 → 引擎这个 404 实测不带 Cache-Control →
  //   被 Chromium 当可启发式缓存的状态码写进磁盘缓存 → 前端取缩略图用的是
  //   fetch(url, {cache:'force-cache'})（comfyui_frontend_package 的 MediaCacheService）,
  //   只认缓存、不回源也不校验 → 之后即使把缩略图补装齐全（200），画布里仍是永久占位图。
  // 所以 media-* 数量在这里当硬指标核对，别等模板库整片占位才发现。
  const templates = tryRun(venvPython, ['-c', 'import comfyui_workflow_templates as t;print(len(list(t.iter_templates())))'], { cwd: comfyDir })
  check(
    '模板数据 comfyui_workflow_templates 可导入',
    templates.ok,
    templates.ok ? `${templates.out} 个模板` : templates.out.split('\n')[0],
    '跑 npm run setup 补装'
  )

  const sitePackages = venvSitePackages()
  const mediaDists =
    sitePackages && fs.existsSync(sitePackages)
      ? fs.readdirSync(sitePackages).filter((n) => /^comfyui_workflow_templates_media_.*\.dist-info$/.test(n))
      : []
  check(
    '模板缩略图包 media-* 齐全（应有 6 个）',
    mediaDists.length >= 6,
    `${mediaDists.length} 个`,
    '缺缩略图包：跑 npm run setup（会用官方源装全家桶）；若壳里已经出现过整片占位图，补装后再跑 npm run clear:web-cache 清掉先前那份陈旧 404'
  )
}

console.log('\n== 前端：Comfy-Desktop 桌面壳 ==')
check('Comfy-Desktop 就位', fs.existsSync(path.join(desktopDir, 'package.json')), desktopDir, '上游仓库缺失')
const electronExe = path.join(desktopDir, 'node_modules', 'electron', 'dist', isWin ? 'electron.exe' : 'electron')
check('桌面壳依赖已装', fs.existsSync(path.join(desktopDir, 'node_modules')), '', '跑 npm run setup:desktop')
check('Electron 二进制就位', fs.existsSync(electronExe), '', 'pnpm install 没跑 electron 的安装脚本，跑 npm run setup:desktop')

console.log('\n== 接线：安装记录 ==')
const userDataDir = desktopUserDataDir()
const installationsFile = path.join(userDataDir, 'installations.json')
let records = null
try {
  const parsed = JSON.parse(fs.readFileSync(installationsFile, 'utf8'))
  if (Array.isArray(parsed)) records = parsed
} catch {
  records = null
}
check('installations.json 可读', records !== null, installationsFile, '跑 npm run seed')
if (records) {
  const mine = records.find((r) => r && r.id === 'inst-comfyui-local')
  check('已注册本仓 ComfyUI', Boolean(mine), mine ? `${mine.sourceId} @ ${mine.installPath}` : '', '跑 npm run seed')
  if (mine) {
    check('记录里的 venvPath 存在', Boolean(mine.venvPath) && fs.existsSync(mine.venvPath), String(mine.venvPath ?? '-'), '引擎 venv 未就绪，跑 npm run setup')

    // 「起引擎」与「起 comfy-studio 宿主」读的不是同一个字段：
    //   引擎：sources/git.ts 用 venvPath 找 python、用 installPath 找 main.py（<installPath>/main.py
    //         与 <installPath>/ComfyUI/main.py 两种布局都收）；
    //   宿主：lib/comfyStudioHost.ts -> lib/pythonEnv.ts 的 getVenvPythonPath(installPath)
    //         = <installPath>/ComfyUI/.venv/<Scripts|bin>/python，**完全不读 venvPath**。
    // 所以 installPath 写偏一层时，引擎照样能起、面板一开口却报"这个安装没有可用的 venv python"。
    // 本仓布局是仓库根/ComfyUI + 根/ComfyUI/.venv，installPath 就该是仓库根 —— 这里按宿主那条路核。
    const installPath = String(mine.installPath ?? '')
    const derivedPython = path.join(
      installPath,
      'ComfyUI',
      '.venv',
      isWin ? path.join('Scripts', 'python.exe') : path.join('bin', 'python3')
    )
    const derivedMain = path.join(installPath, 'ComfyUI', 'main.py')
    // 比路径不能直接 ===：Windows 上盘符大小写不敏感，记录里存成 D:\... 还是 d:\... 取决于当时
    // 是谁在哪个 shell 里跑 npm run seed（node 拿到的 repoRoot 大小写跟着 cwd 走），同一个目录。
    const sameRoot = isWin ? installPath.toLowerCase() === repoRoot.toLowerCase() : installPath === repoRoot
    check(
      '记录的 installPath 能派生出宿主用的 python 与 main.py',
      sameRoot && fs.existsSync(derivedPython) && fs.existsSync(derivedMain),
      derivedPython,
      `installPath 应为仓库根 ${repoRoot}（宿主只按 <installPath>/ComfyUI/.venv 派生，不读 venvPath）：跑 npm run seed`
    )
  }
}

const failed = results.filter((r) => !r.ok)
console.log(`\n${failed.length === 0 ? '\x1b[32m全部通过\x1b[0m' : `\x1b[31m${failed.length} 项未通过\x1b[0m`}  (共 ${results.length} 项)\n`)
process.exit(failed.length === 0 ? 0 : 1)
