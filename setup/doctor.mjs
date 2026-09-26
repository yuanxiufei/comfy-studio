#!/usr/bin/env node
/**
 * 打通体检：只读检查，不改任何东西。
 *
 * 按「后端(引擎) -> 前端(桌面壳) -> 接线(安装记录)」三段逐项核对，
 * 每项给出 通过/失败 与失败时的下一步命令。任何一项失败都以非 0 退出，
 * 方便在 CI 或脚本里当门禁用。
 */
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'
import { inspect } from './lib/overlay.mjs'

const here = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.dirname(here)
const comfyDir = path.join(repoRoot, 'ComfyUI')
const desktopDir = path.join(repoRoot, 'Comfy-Desktop')
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

// 自己方代码都住在 studio/（父仓库跟踪），靠覆盖层装进两份上游检出的扩展位。
// 这里核对的是「装得对不对、上游有没有漂移」——没装的话后面那些检查会以一个
// 更难懂的方式失败（引擎缺 custom node、桌面壳缺 lib/comfy_studio）。
//
// 两种检出形态（见 setup/lib/overlay.mjs 的 checkoutMode）：
//   独立检出（有 .git）：基线用检出 HEAD 对记录值核对，漂移了就跑 attach --rebaseline。
//   已入库（无独立 .git，内容由父仓跟踪）：没有 HEAD 可对，基线只剩记录值 —— 这种情况下
//   "上游漂移"就体现为父仓的 git diff，所以不拿它当失败，也不假装核对过。
console.log('\n== 覆盖层：自己方代码 ==')
try {
  for (const side of inspect(repoRoot)) {
    const drifted = side.drifted.length
    const missing = side.filesTotal - side.installed - drifted
    const embedded = side.mode === 'embedded'
    const baselineBad = side.baselineOk === false
    const ok = !baselineBad && drifted === 0 && missing === 0 && side.pendingPatches.length === 0 && side.brokenPatches.length === 0
    const recorded = `${side.baselineCommit.slice(0, 7)}${side.upstreamVersion ? ` / 上游 ${side.upstreamVersion}` : ''}`
    const detail =
      (embedded
        ? `已入库（无独立 .git，记录基线 ${recorded}）`
        : baselineBad
          ? `基线漂移（记录 ${side.baselineCommit.slice(0, 7)}，检出 ${side.head.slice(0, 7)}）`
          : '') +
      `文件 ${side.installed}/${side.filesTotal} 就位` +
      (drifted > 0 ? `，${drifted} 个被就地改过` : '') +
      (missing > 0 ? `，待装 ${missing}` : '') +
      (side.droppedPatches.length + side.pendingPatches.length > 0
        ? `，补丁 已打 ${side.droppedPatches.length} 待打 ${side.pendingPatches.length}`
        : '')
    const hint = baselineBad
      ? `上游动过了：核对那几处改动后跑 npm run attach -- --rebaseline`
      : side.brokenPatches.length > 0
        ? `补丁既打不上也退不掉：${side.brokenPatches.join(', ')}（先 git -C ${side.checkout} diff 看清去留）`
        : drifted > 0
          ? `被就地改过的是：${side.drifted.slice(0, 3).join(', ')}${drifted > 3 ? ' …' : ''} —— 搬回 studio/overlay，或用 npm run attach -- --force 顶掉（顶掉前会备份）`
          : missing > 0 || side.pendingPatches.length > 0
            ? '跑 npm run attach 把自己方代码装进检出'
            : ''
    check(`${side.checkout} 覆盖层`, ok, detail, hint)
  }
} catch (err) {
  check('覆盖层可核对', false, String(err?.message ?? err), '先跑 npm run attach -- --check 看覆盖层清单')
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
  // core/json 里、缩略图在 6 个 media-* 包里（setup/install-engine.ps1 第 4 步用官方源装全）。
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
  const mine = records.find((r) => r && r.installPath === comfyDir)
  check('已注册本仓 ComfyUI', Boolean(mine), mine ? `${mine.sourceId} @ ${mine.installPath}` : '', '跑 npm run seed')
  if (mine) {
    check('记录里的 venvPath 存在', Boolean(mine.venvPath) && fs.existsSync(mine.venvPath), String(mine.venvPath ?? '-'), '引擎 venv 未就绪，跑 npm run setup')
  }
}

const failed = results.filter((r) => !r.ok)
console.log(`\n${failed.length === 0 ? '\x1b[32m全部通过\x1b[0m' : `\x1b[31m${failed.length} 项未通过\x1b[0m`}  (共 ${results.length} 项)\n`)
process.exit(failed.length === 0 ? 0 : 1)
