/**
 * 覆盖层装配：把 studio/overlay/<检出名>/ 下的自己人代码装进两份上游检出的
 * 标准扩展位，并把 studio/patches/<检出名>/*.patch 打到上游既有文件上。
 *
 * 两份检出的形态（事实，不是约定）：
 *   上游工作树已经整份收进父仓库（ComfyUI/ 与 Comfy-Desktop/ 里的每个文件都由父仓库跟踪），
 *   所以它们自己没有 .git —— git 只可能把带 .git 的目录记成 gitlink，要把内容入库就必须把
 *   .git 挪走（本机那份在 .cache/upstream-git/<检出名>.git，要恢复成独立检出就搬回去）。
 *   于是自己人代码有两重身份：检出里的那份是"跑起来的样子"，studio/ 里的是它的源。
 *
 * 覆盖层脚本在这种形态下的分工：
 *   attach           把 studio/overlay 的改动同步进检出（幂等）；检出里的就地改动会显式报出来，
 *                    不静默覆盖（--force 顶掉前先备份到 .cache/）。
 *   doctor / --check 只读：自己人代码就位了没、补丁打上了没。
 *   detach           已入库形态直接拒绝：父仓里那份就是工作形态，撤出会把它删成一片删改。
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
  return path.relative(repoRoot, target).split(path.sep).join('/')
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

export function gitTry(args, cwd) {
  try {
    const out = execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] })
    return { ok: true, code: 0, out: out.trim() }
  } catch (err) {
    // out 失败时是 stderr/stdout/err.message 拼的"给人看"的串，别当命令输出用。
    // code 才是 git 的退出码：有些查询把非 0 当"正常空结果"（check-ignore 的 1 =
    // 一个都没被忽略），调用方必须能把它和真出错分开。
    const detail = [err?.stderr, err?.stdout, err?.message].filter(Boolean).join(' ').trim()
    return { ok: false, code: typeof err?.status === 'number' ? err.status : null, out: detail }
  }
}

export function requireGit() {
  const probe = gitTry(['--version'], process.cwd())
  if (!probe.ok) throw new Error(`需要 git（核对检出、打补丁都要走它）：${probe.out}`)
}

function headOf(checkoutDir) {
  const r = gitTry(['rev-parse', 'HEAD'], checkoutDir)
  if (!r.ok) throw new Error(`读不到 ${checkoutDir} 的 HEAD：${r.out}`)
  return r.out
}

/** 归一化后比较路径：git 在 Windows 上回的是正斜杠，大小写也不敏感。 */
function normPath(p) {
  const abs = path.resolve(p).split(/[\\/]/).join(path.sep)
  return process.platform === 'win32' ? abs.toLowerCase() : abs
}

/**
 * 这个目录自己就是一个 git 检出吗？
 * 用来区分"真的上游检出"与"父仓里的 gitlink 空占位目录 / 别的仓库的子目录"——
 * 后者会让 git 一路往上找到别的 HEAD，覆盖层的基线核对与 --rebaseline 都会被带错。
 */
export function isStandaloneCheckout(dir) {
  if (!fs.existsSync(path.join(dir, '.git'))) return false
  const top = gitTry(['rev-parse', '--show-toplevel'], dir)
  return top.ok && normPath(top.out) === normPath(dir)
}

/**
 * 检出形态：
 *   'git'      目录自己就是一个独立的上游检出（有 .git，能读 HEAD、能 --rebaseline）
 *   'embedded' 没有自己的 .git，但落在父仓工作树里、且父仓确实跟踪着它 —— 即"检出已入库"
 *   'alien'    两者都不是：克隆老提交留下的 gitlink 空目录、或别的仓库的子目录
 */
export function checkoutMode(repoRoot, side) {
  const dir = path.join(repoRoot, side.checkout)
  if (!fs.existsSync(dir)) return 'absent'
  if (isStandaloneCheckout(dir)) return 'git'
  const top = gitTry(['rev-parse', '--show-toplevel'], dir)
  if (!top.ok || normPath(top.out) !== normPath(repoRoot)) return 'alien'
  const tracked = gitTry(['ls-files', '--', side.checkout], repoRoot)
  return tracked.ok && tracked.out.length > 0 ? 'embedded' : 'alien'
}

/**
 * 检出目录必须能当上游检出用：要么自己就是独立检出，要么已被父仓整份跟踪。
 *
 * 为什么非要拦 'alien'：克隆父仓（老提交）之后 ComfyUI/ 与 Comfy-Desktop/ 是 gitlink
 * 留下的空目录，它们位于父仓工作树内。此时 git rev-parse HEAD 会一路往上落到父仓，
 * 返回父仓的 HEAD，后果有三：① 基线核对拿父仓 commit 去比上游基线，报出牛头不对马嘴的
 * "漂移"；② attach --rebaseline 会把父仓 commit 写进 studio/upstream.json；
 * ③ 那一侧若没有补丁，attach 还会把自方代码灌进空目录，做出一个"看起来装好了、
 * 其实上游根本不在"的假检出。所以这里宁可停下报错，也不许猜。
 */
function assertCheckoutUsable(repoRoot, side, mode) {
  const dir = path.join(repoRoot, side.checkout)
  const takeover =
    `要一份上游检出（放临时目录就行，本仓不再需要它当检出）：\n` +
    `  git clone ${side.upstream ?? '<上游仓库地址>'} <临时目录>\n` +
    (side.baselineCommit ? `  git -C <临时目录> checkout --detach ${side.baselineCommit}\n` : '')
  if (mode === 'absent') {
    throw new Error(`${side.checkout} 缺失（${dir}），没动盘。\n${takeover}`)
  }
  if (mode === 'alien') {
    throw new Error(
      `${side.checkout} 既不是独立检出、也没被父仓跟踪（${dir}），没动盘：\n` +
        `  这是克隆老提交留下的 gitlink 空目录、或者别的仓库的子目录 —— 两种情况都会让 git 一路\n` +
        `  往上找到别的 HEAD，把基线核对与 --rebaseline 带错，所以这里宁可停下报错，也不许猜。\n${takeover}`
    )
  }
}

/** 一侧的形态 + 基线，说成人话（attach / doctor / --check 共用，别各自拼字符串）。 */
export function modeLabel(plan) {
  const side = plan.side
  const recorded =
    `${side.baselineCommit ? side.baselineCommit.slice(0, 7) : '未记'}` +
    (side.upstreamVersion ? ` / 上游 ${side.upstreamVersion}` : '')
  if (plan.mode === 'git') return `独立检出 ${plan.head.slice(0, 7)}（记录基线 ${recorded}）`
  return `已入库、无独立 .git（内容由父仓跟踪；记录基线 ${recorded}）`
}

/**
 * 只读计划：这一侧要装哪些文件、每个目标文件现在是什么状态、补丁打没打上。
 * state：missing（还没装）/ same（已就位且与覆盖层一致）/ differs（存在但被就地改过）。
 * 补丁 state：applied（已打上）/ absent（干净未打）/ conflict（既打不上也退不掉）。
 */
export function planSide(repoRoot, side) {
  const mode = checkoutMode(repoRoot, side)
  assertCheckoutUsable(repoRoot, side, mode)
  const checkoutDir = path.join(repoRoot, side.checkout)
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
  // head 只对独立检出有意义。已入库形态没有自己的 HEAD：在检出目录里跑 rev-parse HEAD
  // 会落到父仓头上，所以这里宁可给 null，也不拿父仓 commit 冒充上游检出。
  return { side, mode, head: mode === 'git' ? headOf(checkoutDir) : null, checkoutDir, overlayRoot, files, patches }
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

/**
 * 这批文件里哪些被 git 忽略（父仓工作树口径）。
 * 被忽略的新文件连 git status 都不显示，必须显式 git add -f —— 所以要把它们挑出来点名，
 * 否则"自己方代码不会丢"只对已入库的旧文件成立，新文件会静默漏掉。
 *
 * 返回 null = 没能确认（git check-ignore 非正常退出）：调用方必须显式报出来，
 * 不许当成"一个都没被忽略"——那正好是把新文件放跑的方向。
 *
 * cwd 决定"在哪个 git 工作树里问"：已入库形态问父仓（rel 带检出名前缀），
 * 独立检出问检出自己那个仓（rel 就是检出内路径）——两边的 .gitignore 规则各归各的。
 */
function ignoredAmong(cwd, rels) {
  if (rels.length === 0) return []
  const r = gitTry(['check-ignore', '--', ...rels], cwd)
  if (r.ok) return r.out.split('\n').filter(Boolean)
  // 退出码 1 是正常"空结果"：没有任何路径被 .gitignore 匹配上。
  // 不能拿 r.out 判断：失败时它是 "Command failed: …" 那段给人看的串，会被当成忽略名单。
  if (r.code === 1) return []
  return null
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
  if (plan.mode !== 'git') {
    throw new Error(`${plan.side.checkout} 不是独立检出（${plan.mode}），读不到上游 commit，不能自动重写基线`)
  }
  const side = plan.side
  side.baselineCommit = plan.head
  side.baselineSubject = gitTry(['log', '-1', '--pretty=%s'], plan.checkoutDir).out
  const branch = gitTry(['rev-parse', '--abbrev-ref', 'HEAD'], plan.checkoutDir).out
  if (branch && branch !== 'HEAD') side.baselineBranch = branch
  saveManifest(repoRoot, manifest)
  log(
    `     基线已重新对齐到 ${plan.head.slice(0, 7)}（${side.baselineSubject}）` +
      `  ——补丁还合不合得上由这次装配当场验证`
  )
}

function assertBaseline(repoRoot, manifest, plan, { rebaseline, log }) {
  if (plan.mode === 'embedded') {
    // 检出已入库时没有独立 HEAD 可读：基线不再靠检出 commit 核对，而是靠父仓 diff
    // （父仓里那份 = 入库时的内容），上游换版本只能手改 studio/upstream.json。
    if (rebaseline) {
      throw new Error(
        `${plan.side.checkout} 已入库（没有独立 .git），读不到上游 commit，不会替你写基线：\n` +
          `  上游换成别的 commit 之后，手改 studio/upstream.json 里这一侧的\n` +
          `  baselineCommit / baselineBranch / upstreamVersion / baselineSubject，\n` +
          `  再跑 npm run doctor 核对补丁还合不合得上。`
      )
    }
    log(`[i]    ${plan.side.checkout} ${modeLabel(plan)}`)
    return
  }
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
    const created = []
    for (const f of plan.files) {
      if (f.state === 'same') {
        kept++
        continue
      }
      fs.mkdirSync(path.dirname(f.dst), { recursive: true })
      fs.copyFileSync(f.src, f.dst)
      written++
      if (f.state === 'missing') created.push(f.rel)
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
      `[attach] ${plan.side.checkout} ${modeLabel(plan)} 就位：` +
        `文件 新增/更新 ${written}，已就绪 ${kept}` +
        (plan.patches.length > 0 ? `，补丁 新打 ${patched}/${plan.patches.length}` : '，无补丁')
    )
    if (written > 0 || patched > 0) {
      // 两种形态在"新文件"上会栽同一个跟头：落点在被 .gitignore 忽略的目录里时，新文件连
      // git status 都不显示，不显式强加就会静默漏掉。区别只是"在哪个仓里加"——所以这条提醒
      // 不能只给已入库形态：独立检出一样会漏，只是路径得按检出自己那个仓给（父仓根下的
      // ComfyUI/... 在那边是无效 pathspec）。
      const inCheckout = plan.mode === 'git'
      const addCmd = inCheckout ? `git -C ${plan.side.checkout} add -f` : `git add -f`
      log(
        inCheckout
          ? `[!]    ${plan.side.checkout} 是独立检出：改动在检出自己的 git 里，用` +
            ` git -C ${plan.side.checkout} status 看，确认无误就提交`
          : `[!]    ${plan.side.checkout} 的内容由父仓跟踪：已跟踪文件那部分改动在仓库根用` +
            ` git status -- ${plan.side.checkout} 能看到，确认无误就连同 studio/ 一起提交`
      )
      const ignored = ignoredAmong(
        inCheckout ? plan.checkoutDir : repoRoot,
        inCheckout ? created : created.map((rel) => `${plan.side.checkout}/${rel}`)
      )
      if (ignored === null) {
        // 这是装配完之后的提醒，不是装配本身：确认不了就明说，别让 attach 拿它假装成功，
        // 也别因为一句提醒失败就把已装好的结果否掉。真门禁在 npm run doctor（它按父仓
        // 跟踪状态判，不依赖 .gitignore，确认不出来的情况它照样抓得到）。
        log(
          `[!]    没能确认这批新文件会不会被上游 .gitignore 吞掉（git check-ignore 非正常退出）。\n` +
            `      别跳过：跑 npm run doctor，它按父仓跟踪状态核对覆盖层里每个文件都被跟踪。`
        )
      } else if (ignored.length > 0) {
        log(
          `[!]    另有 ${ignored.length} 个新文件落在上游 .gitignore 的忽略范围里 —— 那些连\n` +
            `      git status 都不显示，不显式强加就会静默漏掉（老问题会只在新文件上复发）。现在就加：\n` +
            `      ${addCmd} ${ignored.join(' ')}`
        )
      }
    }
  }
}

/** 把覆盖层与补丁撤出检出，让独立检出回到基线原样。已入库的那些一侧直接拒绝（见下）。 */
export function detach(repoRoot, { force = false, log = console.log } = {}) {
  requireGit()
  const manifest = loadManifest(repoRoot)
  const plans = manifest.sides.map((side) => planSide(repoRoot, side))

  // 已入库形态不能 detach：父仓里那份本来就是"装了覆盖层"的工作形态，撤出等于把它
  // 删成一片删改（那些文件父仓跟踪着），既不是"回到上游原样"，还容易连带提交。
  const embedded = plans.filter((plan) => plan.mode === 'embedded')
  if (embedded.length > 0) {
    throw new Error(
      embedded
        .map(
          (plan) =>
            `${plan.side.checkout} 已入库（没有独立 .git），没动盘：撤出会把它删成一片删改。\n` +
            `  要纯净上游做对比：git clone ${plan.side.upstream ?? '<上游仓库地址>'} <临时目录>` +
            (plan.side.baselineCommit ? `，再 git -C <临时目录> checkout --detach ${plan.side.baselineCommit}` : '') +
            `\n  要把检出恢复成入库时的样子：git -C ${plan.side.checkout} restore .`
        )
        .join('\n')
    )
  }

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
      mode: plan.mode,
      upstream: side.upstream ?? null,
      upstreamVersion: side.upstreamVersion ?? null,
      baselineCommit: side.baselineCommit,
      // 已入库形态没有自己的 HEAD：基线核对比不了，给 null（调用方据此改口径，别当失败也别当通过）。
      baselineOk: plan.mode === 'git' ? plan.head === side.baselineCommit : null,
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
