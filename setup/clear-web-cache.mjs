#!/usr/bin/env node
/**
 * 清掉 Comfy-Desktop 桌面壳的浏览器缓存（排障用，一次性）。
 *
 * 什么时候需要它（以下每条都是上游源码/实测事实，不是猜的）：
 *
 *   - 画布模板缩略图的 URL 由前端自己拼：`/templates/<name>-1.<mediaSubtype>`
 *     （comfyui_frontend_package 的 getTemplateThumbnailUrl），取图走
 *     `fetch(url, { cache: 'force-cache' })`（同包的 MediaCacheService.getCachedMedia）。
 *   - 引擎这条路由在缩略图包缺失时对每个 URL 抛 404
 *     （ComfyUI/app/frontend_management.py: serve_template -> web.HTTPNotFound），
 *     实测该 404 **不带 Cache-Control**（ComfyUI/middleware/cache_middleware.py 的
 *     404 分支只覆盖「handler 直接 return 404」的情形，抛异常走不到那里）。
 *     不带显式时效的 404 属于可启发式缓存的状态码，Chromium 照样把它写进磁盘缓存。
 *   - 之后 `force-cache` 只认缓存、不回源也不校验：补装缩略图包、引擎已 200 也白搭，
 *     模板库里永远是同一张占位图，重启也不恢复。
 *
 * 处置就是删掉那份缓存。两个上游仓库零改动：这里只动 Electron userData 下的缓存目录，
 * 不碰 Cookie / IndexedDB / Local Storage / Network —— 登录态、安装记录都在后者里。
 *
 * 用法：
 *   npm run clear:web-cache            先关掉桌面壳再跑，然后重新 npm run dev
 *   npm run clear:web-cache -- --dry-run   只看会删什么，不真删
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import process from 'node:process'

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

/**
 * 纯缓存目录白名单 —— 只列「删了只会重新下载/重建」的那些。
 * 刻意不含 Cookies / Network / IndexedDB / Local Storage / Session Storage / WebStorage /
 * Preferences / Local State：登录态、安装记录、前端设置都在那边。
 */
const CACHE_DIR_NAMES = [
  'Cache',
  'Code Cache',
  'GPUCache',
  'DawnGraphiteCache',
  'DawnWebGPUCache',
  'Shared Dictionary'
]

const dryRun = process.argv.includes('--dry-run')

const userDataDir = desktopUserDataDir()
if (!fs.existsSync(userDataDir)) {
  console.log(`\n[OK] 没有 userData 目录，无需清理：${userDataDir}`)
  console.log('     （桌面壳还没首启过）\n')
  process.exit(0)
}

// 除默认 session 外，每个持久分区（Partitions/<name>，如 shared）各有一份独立缓存。
const roots = [userDataDir]
const partitionsDir = path.join(userDataDir, 'Partitions')
if (fs.existsSync(partitionsDir)) {
  for (const name of fs.readdirSync(partitionsDir)) {
    const dir = path.join(partitionsDir, name)
    if (fs.statSync(dir).isDirectory()) roots.push(dir)
  }
}

function dirSizeBytes(dir) {
  let total = 0
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    try {
      if (entry.isDirectory()) total += dirSizeBytes(full)
      else total += fs.statSync(full).size
    } catch {
      // 读不到的条目按 0 算，只影响展示的字节数
    }
  }
  return total
}

const mb = (bytes) => `${(bytes / (1024 * 1024)).toFixed(2)} MB`
let removedCount = 0
let freedBytes = 0
const failures = []

console.log(`\nuserData: ${userDataDir}`)
console.log(dryRun ? '模式    : --dry-run（只看，不删）\n' : '模式    : 真删\n')

for (const root of roots) {
  const label = path.relative(userDataDir, root) || '.'
  let reported = false
  for (const name of CACHE_DIR_NAMES) {
    const target = path.join(root, name)
    if (!fs.existsSync(target)) continue
    if (!reported) {
      console.log(`[${label}]`)
      reported = true
    }
    const size = dirSizeBytes(target)
    if (dryRun) {
      console.log(`  - 将删除 ${name}  (${mb(size)})`)
      freedBytes += size
      removedCount += 1
      continue
    }
    try {
      fs.rmSync(target, { recursive: true, force: true })
      console.log(`  - 已删除 ${name}  (${mb(size)})`)
      freedBytes += size
      removedCount += 1
    } catch (err) {
      failures.push({ target, message: String(err?.message ?? err) })
      console.log(`  ! 删不掉 ${name}  -> ${err?.code ?? err?.message ?? err}`)
    }
  }
}

if (removedCount === 0 && failures.length === 0) {
  console.log('[--] 没找到任何缓存目录，可能已经被清过。\n')
  process.exit(0)
}

if (failures.length > 0) {
  console.error(`\n[X] ${failures.length} 个缓存目录删不掉。`)
  console.error('    -> 桌面壳（Electron）还开着，缓存文件被进程锁住了：先完全退出壳再重跑。')
  for (const f of failures) console.error(`       ${f.target}`)
  process.exit(1)
}

console.log(`\n[OK] ${dryRun ? '待清理' : '已清理'} ${removedCount} 个目录，共 ${mb(freedBytes)}。`)
console.log('     陈旧 404 随磁盘缓存一起没了，模板缩略图会重新回源取。')
console.log('     下一步：npm run dev（首次进模板库会比平时慢一点，属正常重下）\n')
