#!/usr/bin/env node
/**
 * 打通体检：只读检查，不改仓库里任何东西（唯一例外是 node_modules/.cache 下的门禁缓存，
 * 加 --no-cache 连它也不写）。
 *
 * 按「自己人代码入库 -> 后端(引擎) -> 前端(桌面壳) -> 接线(安装记录)」四段逐项核对，
 * 每项给出 通过/失败 与失败时的下一步命令。任何一项失败都以非 0 退出，
 * 方便在 CI 或脚本里当门禁用。
 *
 * 参数：
 *   --fast      跳过两条重型门禁（typecheck / lint），只留快检项
 *   --no-cache  重型门禁按上游原样冷跑，不读也不写 node_modules/.cache 下的缓存
 */
import { execFileSync, spawn } from 'node:child_process'
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

// 参数：--fast 跳过重型门禁（赶时间时用）；--no-cache 不碰缓存、按上游原样冷跑。
const argv = process.argv.slice(2)
const unknownArgs = argv.filter((a) => a !== '--fast' && a !== '--no-cache')
if (unknownArgs.length > 0) {
  console.error(`未知参数：${unknownArgs.join(' ')}（doctor 只认 --fast / --no-cache）`)
  process.exit(2)
}
const FAST = argv.includes('--fast')
const NO_CACHE = argv.includes('--no-cache')
// 总耗时也报出来：门禁提速（并发 + 缓存）是不是还成立，一眼能看出来
const runStarted = Date.now()

const results = []
const skipped = []
function check(name, ok, detail = '', hint = '') {
  results.push({ name, ok, detail, hint })
  const mark = ok ? '\x1b[32m[OK]\x1b[0m' : '\x1b[31m[--]\x1b[0m'
  console.log(`${mark} ${name}${detail ? `  ${detail}` : ''}`)
  if (!ok && hint) console.log(`       -> ${hint}`)
}

/** 被 --fast 跳过的项：显式打出来（跳过也要看得见），且不计入通过/失败。 */
function skip(name, why) {
  skipped.push(name)
  console.log(`\x1b[33m[跳过]\x1b[0m ${name}  （${why}）`)
}

// ── 上游 .husky/pre-commit 的三件套：typecheck -> lint -> format:check ──────────────────────────
// 本仓是「两份上游检出整份收在父仓」的布局：Comfy-Desktop 下没有 .git，husky 装出来的钩子落不进
// 父仓的 .git/hooks（core.hooksPath 也没设），所以这三条一直没人跑。三条都由 doctor 机械兜住，
// 判定口径与上游 package.json 的 npm script 逐字对齐（同一条 glob、同一组 -p/--composite false）。
//
// 代价与提速（都不改变判定口径）。2026-09-28 本机实测冷跑：eslint . 20.5s，四段 tsc 合计 12.0s
// （node 4.2 / web 4.7 / e2e 1.1 / integration 2.0）。串起来加进体检会把 10s 级拖成 40s 级，所以：
//   1) 并发：四段 tsc 与 eslint 在这里就起，和下面整段文件核对/python 检查并行跑，总耗时只取决于
//      最慢那条（冷跑 ~20s，热跑 ~2s），不是把它们首尾相接累加；
//   2) 缓存：eslint --cache（content 策略，按内容哈希判定，不靠 mtime）与 tsc --incremental 落在
//      node_modules/.cache/comfy-studio-doctor/（node_modules 本就在上游 .gitignore 里，不进库）。
//      缓存只加速、不跳过：内容或配置变了照样重算，热跑实测 eslint 1.0s、四段 tsc 5.0s。
//      --no-cache 按上游原样冷跑；单条超时 5 分钟算失败，不让体检无限等。
const GATE_TIMEOUT_MS = 5 * 60 * 1000
const gateCacheDir = path.join(desktopDir, 'node_modules', '.cache', 'comfy-studio-doctor')
const gateCache = { ok: false, why: '' }
if (NO_CACHE) {
  gateCache.why = '--no-cache'
} else {
  try {
    fs.mkdirSync(gateCacheDir, { recursive: true })
    gateCache.ok = true
  } catch (err) {
    // 缓存建不出来就退化成冷跑，但必须说出来，不许静默降级
    gateCache.why = `缓存目录建不出来：${err.message}`
  }
}

/** 起一个门禁子进程；返回 Promise 但不 await —— 它和体检其它项并行跑。 */
function startGate(name, binRel, args) {
  const bin = path.join(desktopDir, 'node_modules', ...binRel)
  const started = Date.now()
  if (!fs.existsSync(bin)) {
    return Promise.resolve({
      name,
      ok: false,
      out: `缺 ${bin}（跑 npm run setup:desktop）`,
      seconds: 0
    })
  }
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [bin, ...args], {
      cwd: desktopDir,
      env: { ...process.env, NO_COLOR: '1' },
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true
    })
    let out = ''
    let timedOut = false
    const timer = setTimeout(() => {
      timedOut = true
      child.kill()
    }, GATE_TIMEOUT_MS)
    const finish = (ok) => {
      clearTimeout(timer)
      resolve({ name, ok, out, seconds: (Date.now() - started) / 1000 })
    }
    child.stdout.on('data', (chunk) => (out += chunk))
    child.stderr.on('data', (chunk) => (out += chunk))
    child.on('error', (err) => {
      out += String(err?.message ?? err)
      finish(false)
    })
    child.on('close', (code) => {
      if (timedOut) out += `\n超过 ${GATE_TIMEOUT_MS / 1000}s 没跑完，已杀掉`
      else if (code !== 0 && out.trim() === '') out += `退出码 ${code}，无输出`
      finish(code === 0 && !timedOut)
    })
  })
}

// 四段与上游 package.json 的 typecheck:* 逐字一致（上游 tsconfig 里 composite 是 true，脚本在命令行
// 按 false 覆盖 —— 这里照抄，不许自创口径）
const TS_GATES = [
  {
    name: 'node',
    bin: ['typescript', 'bin', 'tsc'],
    args: ['--noEmit', '-p', 'tsconfig.node.json', '--composite', 'false']
  },
  {
    name: 'web',
    bin: ['vue-tsc', 'bin', 'vue-tsc.js'],
    args: ['--noEmit', '-p', 'tsconfig.web.json', '--composite', 'false']
  },
  {
    name: 'e2e',
    bin: ['typescript', 'bin', 'tsc'],
    args: ['--noEmit', '-p', 'tsconfig.e2e.json', '--composite', 'false']
  },
  {
    name: 'integration',
    bin: ['typescript', 'bin', 'tsc'],
    args: ['--noEmit', '-p', 'tsconfig.vitest-integration.json', '--composite', 'false']
  }
]

// 格式门禁的 glob：前两条照上游 format:check 原样，第三条是自家脚本（上游 glob 只到 src/** 和根上的
// json/ts/yml，够不着 scripts/comfy-studio 下的 .mjs）
const fmtScopes = ['src/**/*.{ts,vue}', '*.{json,ts,yml}', 'scripts/comfy-studio/**/*.mjs']

// 现在就起（桌面壳那一段才取结果）：四段 tsc / eslint / prettier 同时跑。
// 这里千万别用 spawnSync —— 同步调用会把 node 的事件循环堵住，子进程明明早就结束了，'close' 事件
// 却要等堵完才被处理，量出来的耗时全变成"堵了多久"（2026-09-28 踩过：四个 tsc 全报 11.1s，而实际
// 只跑了 4~5s）。耗时是墙上时间，体检里还有几处同步 python 检查会短暂堵一下事件循环，秒数偶尔偏大
// 一点点，不影响判定。
const gates = {
  prettier: startGate(
    'prettier',
    ['prettier', 'bin', 'prettier.cjs'],
    [
      '--check',
      ...(gateCache.ok
        ? ['--cache', '--cache-location', path.join(gateCacheDir, 'prettier-cache')]
        : []),
      ...fmtScopes
    ]
  ),
  ts: FAST
    ? null
    : Promise.all(
        TS_GATES.map((g) =>
          startGate(g.name, g.bin, [
            ...g.args,
            ...(gateCache.ok
              ? [
                  '--incremental',
                  '--tsBuildInfoFile',
                  path.join(gateCacheDir, `ts-${g.name}.tsbuildinfo`)
                ]
              : [])
          ])
        )
      ),
  eslint: FAST
    ? null
    : startGate(
        'eslint',
        ['eslint', 'bin', 'eslint.js'],
        [
          '.',
          ...(gateCache.ok
            ? [
                '--cache',
                '--cache-strategy',
                'content',
                '--cache-location',
                path.join(gateCacheDir, 'eslint-cache')
              ]
            : [])
        ]
      )
}

function tryRun(file, args, opts = {}) {
  try {
    return {
      ok: true,
      out: execFileSync(file, args, {
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'ignore'],
        ...opts
      }).trim()
    }
  } catch (err) {
    return { ok: false, out: String(err?.message ?? err) }
  }
}

function desktopUserDataDir() {
  if (process.platform === 'win32') {
    return path.join(
      process.env.APPDATA ?? path.join(os.homedir(), 'AppData', 'Roaming'),
      'comfyui-desktop-2'
    )
  }
  if (process.platform === 'darwin') {
    return path.join(os.homedir(), 'Library', 'Application Support', 'comfyui-desktop-2')
  }
  return path.join(
    process.env.XDG_CONFIG_HOME ?? path.join(os.homedir(), '.config'),
    'comfyui-desktop-2'
  )
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
      check(
        `${side.checkout} 接线补丁在位`,
        false,
        path.basename(patch),
        `自述的 patch 字段指着 ${patch}，但它不在`
      )
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
check(
  'Node 版本 >= 22',
  Number(process.versions.node.split('.')[0]) >= 22,
  `v${process.versions.node}`
)
check('ComfyUI 就位', fs.existsSync(path.join(comfyDir, 'main.py')), comfyDir, '上游仓库缺失')
check('引擎 venv 存在', fs.existsSync(venvPython), venvPython, '跑 npm run setup')

if (fs.existsSync(venvPython)) {
  // 注意：内联 Python 只用单引号，避免双引号在 Windows 的 argv 重组里被拆坏
  const probe = tryRun(
    venvPython,
    [
      '-c',
      "import torch,sys;gpu=torch.cuda.get_device_name(0) if torch.cuda.is_available() else '-';print('torch=%s cuda_build=%s cuda_ready=%s gpu=%s'%(torch.__version__,torch.version.cuda,torch.cuda.is_available(),gpu))"
    ],
    { cwd: comfyDir }
  )
  check(
    'torch 可导入',
    probe.ok,
    probe.ok ? probe.out : probe.out.split('\n')[0],
    'pip 装失败时看 .cache/engine-torch.log'
  )
  if (probe.ok && probe.out.includes('cuda_ready=False')) {
    console.log(
      '       !! torch 是 CPU 轮子：能跑但吃不到 GPU。要 GPU 重装：npm run setup（带 -TorchIndex cu130）'
    )
  }
  const frontend = tryRun(
    venvPython,
    [
      '-c',
      'import comfyui_frontend_package,os;print(os.path.dirname(comfyui_frontend_package.__file__))'
    ],
    { cwd: comfyDir }
  )
  check(
    '画布前端包 comfyui_frontend_package 可导入',
    frontend.ok,
    frontend.ok ? '' : frontend.out.split('\n')[0],
    '依赖没装全，重跑 npm run setup'
  )

  // 上游 requirements.txt 钉的 comfyui-workflow-templates 只是薄封装，模板数据在
  // core/json 里、缩略图在 6 个 media-* 包里（引擎包里 tools/install-engine.ps1 第 4 步用官方源装全）。
  // 数据缺了只是列表空，缩略图缺了是另一回事，且会留下长尾故障：
  //   /templates/<name>-1.webp 全 404 → 引擎这个 404 实测不带 Cache-Control →
  //   被 Chromium 当可启发式缓存的状态码写进磁盘缓存 → 前端取缩略图用的是
  //   fetch(url, {cache:'force-cache'})（comfyui_frontend_package 的 MediaCacheService）,
  //   只认缓存、不回源也不校验 → 之后即使把缩略图补装齐全（200），画布里仍是永久占位图。
  // 所以 media-* 数量在这里当硬指标核对，别等模板库整片占位才发现。
  const templates = tryRun(
    venvPython,
    ['-c', 'import comfyui_workflow_templates as t;print(len(list(t.iter_templates())))'],
    { cwd: comfyDir }
  )
  check(
    '模板数据 comfyui_workflow_templates 可导入',
    templates.ok,
    templates.ok ? `${templates.out} 个模板` : templates.out.split('\n')[0],
    '跑 npm run setup 补装'
  )

  const sitePackages = venvSitePackages()
  const mediaDists =
    sitePackages && fs.existsSync(sitePackages)
      ? fs
          .readdirSync(sitePackages)
          .filter((n) => /^comfyui_workflow_templates_media_.*\.dist-info$/.test(n))
      : []
  check(
    '模板缩略图包 media-* 齐全（应有 6 个）',
    mediaDists.length >= 6,
    `${mediaDists.length} 个`,
    '缺缩略图包：跑 npm run setup（会用官方源装全家桶）；若壳里已经出现过整片占位图，补装后再跑 npm run clear:web-cache 清掉先前那份陈旧 404'
  )
}

console.log('\n== 前端：Comfy-Desktop 桌面壳 ==')
check(
  'Comfy-Desktop 就位',
  fs.existsSync(path.join(desktopDir, 'package.json')),
  desktopDir,
  '上游仓库缺失'
)
const electronExe = path.join(
  desktopDir,
  'node_modules',
  'electron',
  'dist',
  isWin ? 'electron.exe' : 'electron'
)
check(
  '桌面壳依赖已装',
  fs.existsSync(path.join(desktopDir, 'node_modules')),
  '',
  '跑 npm run setup:desktop'
)
check(
  'Electron 二进制就位',
  fs.existsSync(electronExe),
  '',
  'pnpm install 没跑 electron 的安装脚本，跑 npm run setup:desktop'
)

// 三条门禁按上游 .husky/pre-commit 的顺序打印：typecheck -> lint -> format:check。三条都在文件顶部
// 就并发起了（见那里的说明），一直和上面整段检查并行跑，这里只是取结果 + 判定。
// 输出可能带 ANSI 颜色，判定前先剥掉（同时用 NO_COLOR 让它们别上色）。
// （2026-09-28 实测：自家 4 个 TS 文件早就漂了 —— 盘上 CRLF、长行没折，而 tsc 与 eslint 照样全绿，
// 所以三条谁也替不了谁。）
const stripAnsi = (s) =>
  s
    .split('\u001b[')
    .map((part, i) => (i === 0 ? part : part.replace(/^[0-9;]*m/, '')))
    .join('')
const gateMode = gateCache.ok
  ? '带缓存'
  : NO_CACHE
    ? '冷跑（--no-cache）'
    : `冷跑（${gateCache.why}）`
const gateLines = (out) =>
  stripAnsi(out)
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)

if (FAST) {
  skip('类型门禁 typecheck（四段）', '--fast')
  skip('Lint 门禁 eslint .', '--fast')
} else {
  const tsResults = await gates.ts
  const badTs = tsResults.filter((r) => !r.ok)
  const firstTsError = badTs.length
    ? (gateLines(badTs[0].out).find((l) => /error TS\d+/.test(l)) ??
      '没有 error TS 行，看该段首行输出')
    : ''
  check(
    '类型门禁 typecheck 四段全绿',
    badTs.length === 0,
    badTs.length === 0
      ? `${tsResults.map((r) => `${r.name} ${r.seconds.toFixed(1)}s`).join(' / ')}（四段并发，${gateMode}）`
      : `${badTs.map((r) => r.name).join('、')} 未过：${firstTsError.slice(0, 150)}`,
    'cwd 在 Comfy-Desktop：npm run typecheck（node/web/e2e/integration 四段，与上游 package.json 同口径）'
  )

  const lint = await gates.eslint
  const lintLines = gateLines(lint.out)
  check(
    'Lint 门禁 eslint . 通过',
    lint.ok,
    lint.ok
      ? `${lint.seconds.toFixed(1)}s（${gateMode}）`
      : [lintLines.find((l) => /\d+:\d+/.test(l)), lintLines.at(-1)]
          .filter(Boolean)
          .join('  |  ')
          .slice(0, 150),
    'cwd 在 Comfy-Desktop：npm run lint（eslint .，与上游同口径）'
  )
}

// 格式门禁：prettier 没有缓存，耗时就是它的墙上时间
const pf = await gates.prettier
const pfLines = gateLines(pf.out)
// prettier 的收尾汇总行也带 [warn] 前缀（"Code style issues found in ..."），别把它算成文件名
const pfDirty = pfLines
  .filter((l) => l.startsWith('[warn]') && !l.includes('Code style issues found'))
  .map((l) => l.slice('[warn]'.length).trim())
check(
  '格式门禁 prettier --check 通过',
  pf.ok,
  pf.ok
    ? `${pf.seconds.toFixed(1)}s`
    : pfDirty.length > 0
      ? `${pfDirty.length} 个文件不合：${pfDirty.slice(0, 3).join('、')}${pfDirty.length > 3 ? ' …' : ''}`
      : (pfLines.at(-1) ?? ''),
  `cwd 在 Comfy-Desktop：npx prettier --check ${fmtScopes.map((s) => JSON.stringify(s)).join(' ')}`
)

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
  check(
    '已注册本仓 ComfyUI',
    Boolean(mine),
    mine ? `${mine.sourceId} @ ${mine.installPath}` : '',
    '跑 npm run seed'
  )
  if (mine) {
    check(
      '记录里的 venvPath 存在',
      Boolean(mine.venvPath) && fs.existsSync(mine.venvPath),
      String(mine.venvPath ?? '-'),
      '引擎 venv 未就绪，跑 npm run setup'
    )

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
    const sameRoot = isWin
      ? installPath.toLowerCase() === repoRoot.toLowerCase()
      : installPath === repoRoot
    check(
      '记录的 installPath 能派生出宿主用的 python 与 main.py',
      sameRoot && fs.existsSync(derivedPython) && fs.existsSync(derivedMain),
      derivedPython,
      `installPath 应为仓库根 ${repoRoot}（宿主只按 <installPath>/ComfyUI/.venv 派生，不读 venvPath）：跑 npm run seed`
    )
  }
}

const failed = results.filter((r) => !r.ok)
const skippedNote =
  skipped.length > 0 ? `；--fast 跳过 ${skipped.length} 项：${skipped.join('、')}` : ''
const elapsedNote = `，总耗时 ${((Date.now() - runStarted) / 1000).toFixed(1)}s`
console.log(
  `\n${failed.length === 0 ? '\x1b[32m全部通过\x1b[0m' : `\x1b[31m${failed.length} 项未通过\x1b[0m`}  (共 ${results.length} 项${skippedNote}${elapsedNote})\n`
)
process.exit(failed.length === 0 ? 0 : 1)
