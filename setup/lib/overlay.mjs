/**
 * 覆盖层装配：把 studio/overlay/<检出名>/ 下的自己人代码装进两份上游检出的
 * 标准扩展位，并把 studio/patches/<检出名>/*.patch 打到上游既有文件上。
 *
 * 为什么要有覆盖层：
 *   引擎侧代码落在 ComfyUI/custom_nodes/，而上游 ComfyUI 自己的 .gitignore 第 8 行
 *   就忽略 /custom_nodes/；桌面侧新增文件在检出里是未跟踪；父仓库又把两个检出整目录
 *   按 gitlink 忽略、且没有 .gitmodules。三处 git 都不认识这些代码，它们只活在本机
 *   文件系统里。收进 studio/ 后由父仓库跟踪，换机器 clone 下来跑一次 attach 就能复原。
 *
 * 为什么上游那几行改动用补丁、而不是整份文件覆盖：
 *   整份文件覆盖会在上游更新同一文件时静默把上游的改动顶掉；补丁在 git apply --check
 *   阶段就失败，失败即报错，逼人显式处理。
 *
 * 纪律：先只读计划、确认没有冲突再动盘（attach/detach 都不会出现装一半的状态）；
 * 任何一处对不上都显式抛错并说明下一步命令，不静默跳过、不静默顶掉别人的改动；
 * --force 顶掉/删除的内容会先备份到 .cache/ 并在输出里报出路径。
 */
import { execFileSync } from 'node:child_process'
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'

const SKIP_DIRS = new Set(['__pycache__', '.pytest_cache', 'node_modules'])
const SKIP_FILE_RE = /\.(pyc|pyo)$/

/** 读 studio/upstream.json：两侧检出的基线与覆盖层位置。 */
export function loadManifest(repoRoot) {
  const file = path.join(repoRoot, 'studio', 'upstream.json')
  if (!fs.existsSync(file)) throw new Error(`缺少覆盖层清单：${file}`)
  const manifest = JSON.parse(fs.readFileSync(file, 'utf8'))
  if (!Array.isArray(manifest.sides) || manifest.sides.length === 0) {
    throw new Error(`${file} 里 sides 为空，不知道要装配什么`)
  }
  return manifest
}

export function saveManifest(repoRoot, manifest) {
  const file = path.join(repoRoot, 'studio', 'upstream.json')
  fs.writeFileSync(file, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8')
}

/** 提示里给人看的路径：统一成正斜杠，PowerShell 与 bash 里都好复制。 */
function relFrom(repoRoot, target) {
  return relFrom(repoRoot, target).split(path.sep).join('/')
}

function walk(dir, base = dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const abs = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      if (SKIP_DIRS.has(entry.name)) continue
      walk(abs, base, out)
    } else if (entry.isFile() && !SKIP_FILE_RE.test(entry.name)) {
      out.push(path.relative(base, abs).split(path.sep).join('/'))
    }
  }
  return out
}

function sha256(file) {
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
}

function gitTry(args, cwd) {
  try {
    const out = execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] })
    return { ok: true, out: out.trim() }
  } catch (err) {
    const detail = [err?.stderr, err?.stdout, err?.message].filter(Boolean).join(' ').trim()
    return { ok: false, out: detail }
  }
}

export function requireGit() {
  const probe = gitTry(['--version'], process.cwd())
  if (!probe.ok) throw new Error(`需要 git（打补丁走 git apply）：${probe.out}`)
}

function headOf(checkoutDir) {
  const r = gitTry(['rev-parse', 'HEAD'], checkoutDir)
  if (!r.ok) throw new Error(`读不到 ${checkoutDir} 的 HEAD：${r.out}`)
  return r.out
}

/**
 * 只读计划：这一侧要装哪些文件、每个目标文件现在是什么状态、补丁打没打上。
 * state：missing（还没装）/ same（已就位且与覆盖层一致）/ differs（存在但被就地改过）。
 * 补丁 state：applied（已打上）/ absent（干净未打）/ conflict（既打不上也退不掉）。
 */
export function planSide(repoRoot, side) {
  const checkoutDir = path.join(repoRoot, side.checkout)
  if (!fs.existsSync(checkoutDir)) {
    throw new Error(`上游检出缺失：${checkoutDir}（先把它 clone/放到这个位置）`)
  }
  const overlayRoot = path.join(repoRoot, side.overlay ?? '')
  if (!side.overlay || !fs.existsSync(overlayRoot)) {
    throw new Error(`覆盖层源缺失：${overlayRoot}（清单里写的是 ${side.overlay ?? '（空）'}）`)
  }
  const files = walk(overlayRoot).map((rel) => {
    const src = path.join(overlayRoot, rel)
    const dst = path.join(checkoutDir, rel)
    const srcHash = sha256(src)
    const dstHash = fs.existsSync(dst) ? sha256(dst) : null
    return {
      rel,
      src,
      dst,
      srcHash,
      dstHash,
      state: dstHash === null ? 'missing' : dstHash === srcHash ? 'same' : 'differs'
    }
  })
  const patchesDir = side.patches ? path.join(repoRoot, side.patches) : null
  const patches =
    patchesDir && fs.existsSync(patchesDir)
      ? fs
          .readdirSync(patchesDir)
          .filter((n) => n.endsWith('.patch'))
          .sort()
          .map((name) => {
            const abs = path.join(patchesDir, name)
            const applied = gitTry(['apply', '--check', '--reverse', abs], checkoutDir).ok
            const clean = applied ? false : gitTry(['apply', '--check', abs], checkoutDir).ok
            return { name, abs, state: applied ? 'applied' : clean ? 'absent' : 'conflict' }
          })
      : []
  return { side, checkoutDir, overlayRoot, files, patches, head: headOf(checkoutDir) }
}

/** 顶掉别人的改动之前先备份，并把备份目录报出来。 */
function backupBeforeDamage(repoRoot, entries, kind) {
  const stamp = new Date().toISOString().replace(/[:.]/g, '-')
  const dir = path.join(repoRoot, '.cache', `overlay-${kind}-${stamp}`)
  entries.forEach((entry, i) => {
    const target = path.join(dir, String(i).padStart(3, '0'), path.basename(entry.rel))
    fs.mkdirSync(path.dirname(target), { recursive: true })
    if (fs.existsSync(entry.dst)) fs.copyFileSync(entry.dst, target)
  })
  return dir
}

function removeEmptyDirs(dirs, stopAt) {
  const sorted = [...new Set(dirs)].sort((a, b) => b.length - a.length)
  for (const dir of sorted) {
    let cur = dir
    while (cur.length > stopAt.length && fs.existsSync(cur)) {
      if (fs.readdirSync(cur).length > 0) break
      fs.rmdirSync(cur)
      cur = path.dirname(cur)
    }
  }
}

function rewriteBaseline(repoRoot, manifest, plan, log) {
  const side = plan.side
  side.baselineCommit = plan.head
  side.baselineSubject = gitTry(['log', '-1', '--pretty=%s'], plan.checkoutDir).out
  saveManifest(repoRoot, manifest)
  log(
    `     基线已重新对齐到 ${plan.head.slice(0, 7)}（${side.baselineSubject}）` +
      `  ——补丁还合不合得上由这次装配当场验证`
  )
}

function assertBaseline(repoRoot, manifest, plan, { rebaseline, log }) {
  if (plan.head === plan.side.baselineCommit) return
  if (rebaseline) {
    log(`[!]    ${plan.side.checkout} 检出已不在记录的基线上：`)
    log(`     记录基线 ${plan.side.baselineCommit.slice(0, 7)}（${plan.side.baselineSubject}）`)
    log(`     当前检出 ${plan.head.slice(0, 7)}`)
    rewriteBaseline(repoRoot, manifest, plan, log)
    return
  }
  throw new Error(
    `${plan.side.checkout} 的检出不在记录的基线上，没动盘：\n` +
      `  记录基线 ${plan.side.baselineCommit}（${plan.side.baselineSubject}）\n` +
      `  当前检出 ${plan.head}\n` +
      `  上游更新过就重新对齐：npm run attach -- --rebaseline（会当场验证补丁还合不合得上）\n` +
      `  想退回基线：git -C ${plan.side.checkout} checkout ${plan.side.baselineCommit}`
  )
}

/** 把覆盖层装进检出、把补丁打上去。可重复执行：已就位的文件与已打上的补丁直接跳过。 */
export function attach(repoRoot, { force = false, rebaseline = false, log = console.log } = {}) {
  requireGit()
  const manifest = loadManifest(repoRoot)
  const plans = manifest.sides.map((side) => planSide(repoRoot, side))

  // 第一步：只读核对，任何一处对不上都在这里一次性报全，绝不装一半。
  for (const plan of plans) {
    assertBaseline(repoRoot, manifest, plan, { rebaseline, log })
    const clashed = plan.patches.filter((p) => p.state === 'conflict')
    if (clashed.length > 0) {
      throw new Error(
        `${plan.side.checkout} 的补丁既打不上也退不掉（上游这几个文件被改过），没动盘：\n` +
          clashed.map((p) => `  ${p.name}`).join('\n') +
          `\n  先看 git -C ${plan.side.checkout} diff，确认那几处改动要留还是丢：\n` +
          `  留就把它们并回 ${relFrom(repoRoot, plan.side.patches)} 里的补丁，丢就 git -C ${plan.side.checkout} checkout -- <文件>`
      )
    }
    const overwrites = plan.files.filter((f) => f.state === 'differs')
    if (overwrites.length > 0 && !force) {
      throw new Error(
        `${plan.side.checkout} 里有 ${overwrites.length} 个文件被就地改过，没动盘：\n` +
          overwrites.map((f) => `  ${f.rel}`).join('\n') +
          `\n  要么把改动搬回 ${relFrom(repoRoot, plan.side.overlay)}，要么加 --force 用覆盖层顶掉（顶掉前会备份到 .cache/）`
      )
    }
  }

  // 第二步：落盘。
  for (const plan of plans) {
    const overwrites = plan.files.filter((f) => f.state === 'differs')
    let backupDir = null
    if (overwrites.length > 0) {
      backupDir = backupBeforeDamage(repoRoot, overwrites, `overwrites-${plan.side.checkout}`)
      log(`[!]   顶掉 ${overwrites.length} 个被就地改过的文件，原内容备份在 ${relFrom(repoRoot, backupDir)}`)
    }
    let written = 0
    let kept = 0
    for (const f of plan.files) {
      if (f.state === 'same') {
        kept++
        continue
      }
      fs.mkdirSync(path.dirname(f.dst), { recursive: true })
      fs.copyFileSync(f.src, f.dst)
      written++
    }
    let patched = 0
    for (const p of plan.patches) {
      if (p.state === 'applied') continue
      const check = gitTry(['apply', '--check', p.abs], plan.checkoutDir)
      if (!check.ok) throw new Error(`补丁打不上：${p.name}（${plan.side.checkout}）\n  ${check.out}`)
      const applied = gitTry(['apply', p.abs], plan.checkoutDir)
      if (!applied.ok) throw new Error(`补丁应用失败：${p.name}\n  ${applied.out}`)
      patched++
    }
    log(
      `[attach] ${plan.side.checkout} 基线 ${plan.head.slice(0, 7)} 就位：` +
        `文件 新增/更新 ${written}，已就绪 ${kept}` +
        (plan.patches.length > 0 ? `，补丁 新打 ${patched}/${plan.patches.length}` : '，无补丁')
    )
  }
}

/** 把覆盖层与补丁撤出检出，让两份上游回到基线原样。 */
export function detach(repoRoot, { force = false, log = console.log } = {}) {
  requireGit()
  const manifest = loadManifest(repoRoot)
  const plans = manifest.sides.map((side) => planSide(repoRoot, side))

  for (const plan of plans) {
    const clashed = plan.patches.filter((p) => p.state === 'conflict')
    if (clashed.length > 0) {
      throw new Error(
        `${plan.side.checkout} 的补丁退不掉，没动盘：\n` +
          clashed.map((p) => `  ${p.name}`).join('\n') +
          `\n  先 git -C ${plan.side.checkout} diff 看清那几处改动，手动决定去留`
      )
    }
    const modified = plan.files.filter((f) => f.state === 'differs')
    if (modified.length > 0 && !force) {
      throw new Error(
        `${plan.side.checkout} 里有 ${modified.length} 个文件与覆盖层不一致（就地改过？），没动盘：\n` +
          modified.map((f) => `  ${f.rel}`).join('\n') +
          `\n  要么把改动搬回 ${relFrom(repoRoot, plan.side.overlay)}，要么加 --force 删掉（删前会备份到 .cache/）`
      )
    }
  }

  for (const plan of plans) {
    let reverted = 0
    for (const p of [...plan.patches].reverse()) {
      if (p.state === 'absent') continue
      const undone = gitTry(['apply', '--reverse', p.abs], plan.checkoutDir)
      if (!undone.ok) throw new Error(`回滚补丁失败：${p.name}\n  ${undone.out}`)
      reverted++
    }
    const modified = plan.files.filter((f) => f.state === 'differs')
    let backupDir = null
    if (modified.length > 0) {
      backupDir = backupBeforeDamage(repoRoot, modified, `removed-${plan.side.checkout}`)
      log(`[!]   删掉 ${modified.length} 个与覆盖层不一致的文件，原内容备份在 ${relFrom(repoRoot, backupDir)}`)
    }
    let removed = 0
    const touchedDirs = []
    for (const f of plan.files) {
      if (f.state === 'missing') continue
      if (f.state === 'same' || force) {
        fs.rmSync(f.dst)
        removed++
        touchedDirs.push(path.dirname(f.dst))
      }
    }
    removeEmptyDirs(touchedDirs, plan.checkoutDir)
    log(
      `[detach] ${plan.side.checkout} 已退回基线 ${plan.head.slice(0, 7)}：` +
        `文件 移除 ${removed}` +
        (plan.patches.length > 0 ? `，补丁 回滚 ${reverted}/${plan.patches.length}` : '，无补丁')
    )
    if (plan.head !== plan.side.baselineCommit) {
      log(`[!]   ${plan.side.checkout} 检出本身不在基线 commit 上（${plan.head.slice(0, 7)}），这次只撤了覆盖层与补丁`)
    }
  }
}

/** 只读体检：给 doctor 用，不抛异常，返回每侧的核对结果。 */
export function inspect(repoRoot) {
  requireGit()
  const manifest = loadManifest(repoRoot)
  return manifest.sides.map((side) => {
    const plan = planSide(repoRoot, side)
    return {
      checkout: side.checkout,
      baselineCommit: side.baselineCommit,
      baselineOk: plan.head === side.baselineCommit,
      head: plan.head,
      filesTotal: plan.files.length,
      installed: plan.files.filter((f) => f.state === 'same').length,
      drifted: plan.files.filter((f) => f.state === 'differs').map((f) => f.rel),
      pendingPatches: plan.patches.filter((p) => p.state === 'absent').map((p) => p.name),
      droppedPatches: plan.patches.filter((p) => p.state === 'applied').map((p) => p.name),
      brokenPatches: plan.patches.filter((p) => p.state === 'conflict').map((p) => p.name)
    }
  })
}
