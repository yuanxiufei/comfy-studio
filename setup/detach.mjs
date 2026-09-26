#!/usr/bin/env node
/**
 * 把覆盖层撤出上游检出：先回滚 studio/patches/ 里的补丁，再删掉 studio/overlay/
 * 装进去的文件（连带清掉因此变空的目录），让检出回到基线原样。
 *
 * 只对**独立检出**（目录里自己的 .git）有效：那种形态下撤出之后检出就是纯净上游。
 * 本仓现在的两份检出是「已入库」形态（工作树整份由父仓跟踪、自己没有 .git），
 * 父仓里那份本来就是"装了覆盖层"的工作形态 —— 在这里撤出只会把它删成一片删改，
 * 所以直接拒绝并给出替代命令（要纯净上游请另 clone 到临时目录）。
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
