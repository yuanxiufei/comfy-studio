#!/usr/bin/env node
/**
 * 把覆盖层装进两份上游检出：studio/overlay/ 里的自己人代码各就各位，
 * studio/patches/ 里的补丁打到上游既有文件上。
 *
 * 为什么要跑它：上游检出整份收在父仓库里，但自己人代码在那两棵树里是"藏着的"：
 *   引擎侧落在 custom_nodes/（被上游 ComfyUI 的 .gitignore 忽略）、
 *   桌面侧对上游既有文件的接线改动是补丁。
 * 改动一律先落在 studio/，再跑一次把它同步进检出（幂等，装好的会跳过）。
 *
 * 用法：
 *   npm run attach                 装（已就位的内容与已打上的补丁自动跳过，可重复执行）
 *   npm run attach -- --check      只看会做什么，不动盘
 *   npm run attach -- --force      顶掉被就地改过的目标文件（顶掉前备份到 .cache/）
 *   npm run attach -- --rebaseline 检出 commit 变了，重新对齐 studio/upstream.json
 *
 * 对不上就报错退出、绝不动盘：不静默跳过，也不静默顶掉别人在上游检出里的改动。
 */
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'
import { attach, inspect } from './lib/overlay.mjs'

const here = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.dirname(here)
const argv = process.argv.slice(2)
const force = argv.includes('--force')
const rebaseline = argv.includes('--rebaseline')
const check = argv.includes('--check')

try {
  if (check) {
    for (const side of inspect(repoRoot)) {
      // mode 'embedded'：检出已入库（没有独立 .git），没有 HEAD 可核对，基线只看记录值。
      const recorded = `${side.baselineCommit.slice(0, 7)}${side.upstreamVersion ? ` / 上游 ${side.upstreamVersion}` : ''}`
      const baseline =
        side.mode === 'embedded'
          ? `已入库（无独立 .git，记录基线 ${recorded}）`
          : side.baselineOk
            ? `基线 ${side.head.slice(0, 7)} ✓`
            : `基线漂移（记录 ${side.baselineCommit.slice(0, 7)}，检出 ${side.head.slice(0, 7)}）`
      const files = `${side.filesTotal} 个文件：已就位 ${side.installed}，待装 ${side.filesTotal - side.installed - side.drifted.length}`
      const patches = side.pendingPatches.length + side.droppedPatches.length + side.brokenPatches.length
      console.log(`[check] ${side.checkout} ${baseline}  ${files}` + (patches > 0 ? `，补丁 待打 ${side.pendingPatches.length}` : ''))
      if (side.drifted.length > 0) {
        console.log(`        被就地改过 ${side.drifted.length} 个：${side.drifted.slice(0, 5).join(', ')}${side.drifted.length > 5 ? ' …' : ''}`)
      }
      if (side.brokenPatches.length > 0) {
        console.log(`        补丁既打不上也退不掉：${side.brokenPatches.join(', ')}`)
      }
    }
  } else {
    attach(repoRoot, { force, rebaseline })
  }
} catch (err) {
  console.error(`\n[X] ${err.message}\n`)
  process.exit(1)
}
