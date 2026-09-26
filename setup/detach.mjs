#!/usr/bin/env node
/**
 * 把覆盖层撤出两份上游检出：先回滚 studio/patches/ 里的补丁，再删掉 studio/overlay/
 * 装进去的文件（连带清掉因此变空的目录），让两份上游回到基线原样。
 *
 * 什么时候用：要 git -C ComfyUI pull 升级上游、要拿上游原始状态复现问题、
 * 或者想确认「跑起来的东西全部来自 studio/ 与上游自身」。
 *
 * 用法：
 *   npm run detach               撤离（可重复执行，已经撤走的自动跳过）
 *   npm run detach -- --force    连同被就地改过的文件一起删（删前备份到 .cache/）
 *
 * 对不上就报错退出、绝不动盘；撤完之后要重新装回来跑 npm run attach。
 */
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'
import { detach } from './lib/overlay.mjs'

const here = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.dirname(here)
const force = process.argv.slice(2).includes('--force')

try {
  detach(repoRoot, { force })
} catch (err) {
  console.error(`\n[X] ${err.message}\n`)
  process.exit(1)
}
