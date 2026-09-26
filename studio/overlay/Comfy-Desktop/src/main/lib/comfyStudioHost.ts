import { EventEmitter } from 'events'
import { spawn, type ChildProcessWithoutNullStreams } from 'child_process'
import fs from 'fs'
import path from 'path'
import { getBundledScriptPath } from './bundledScript'
import { getActivePythonPath } from './pythonEnv'
import type { InstallationRecord } from '../installations'

/**
 * Parent process of `<Comfy-Desktop>/lib/comfy_studio` — the desktop-side
 * comfy-studio host (MCP client + conversation agent) that the panel talks to.
 *
 * One host process per installation. Framing is line-delimited JSON-RPC 2.0 on
 * the child's stdio (stdout carries protocol only; diagnostics go to stderr),
 * see `lib/comfy_studio/rpc.py` for the other side of this contract.
 */

/** Must stay >= the host's own MCP timeout, which defaults to 1800s because a
 *  skill run occupies a single `skills/run` call for its whole duration. */
export const STUDIO_REQUEST_TIMEOUT_MS = 30 * 60 * 1000

/** Grace period between closing the host's stdin (EOF ⇒ clean exit) and killing it. */
export const STUDIO_STOP_GRACE_MS = 2000

export class ComfyStudioError extends Error {
  readonly code: number | undefined

  constructor(message: string, code?: number) {
    super(message)
    this.name = 'ComfyStudioError'
    this.code = code
  }
}

export interface ComfyStudioCommand {
  cmd: string
  args: string[]
  cwd: string
  /** Directory handed to the host as `--comfyui-dir` (the checkout holding `custom_nodes`). */
  comfyuiDir: string
}

export interface ComfyStudioHostOptions {
  /** Extra environment for the child (e.g. COMFY_STUDIO_LLM_MODEL for agent chat). */
  env?: NodeJS.ProcessEnv
  requestTimeoutMs?: number
  /** Receives stderr lines and framing complaints; defaults to console.debug. */
  log?: (line: string) => void
  /** Test seam. */
  spawnImpl?: typeof spawn
}

export interface ComfyStudioNotification {
  method: string
  params: Record<string, unknown>
}

interface PendingRequest {
  method: string
  resolve: (value: unknown) => void
  reject: (error: Error) => void
  timer: NodeJS.Timeout
}

/** `<Comfy-Desktop>/lib`: parent of the `comfy_studio` package, and the cwd that
 *  `-m comfy_studio` needs to resolve the package. */
export function getBundledLibDir(): string {
  return path.dirname(getBundledScriptPath(path.join('comfy_studio', '__main__.py')))
}

/**
 * Directory containing `main.py` for this install: `<installPath>/ComfyUI` in the
 * usual layout, or `installPath` itself when the install *is* a ComfyUI checkout
 * (git-source installs — same probe order as `sources/git.ts`'s `findMainPy`).
 * Returns null rather than guessing when neither exists.
 */
export function findComfyUIDir(installPath: string): string | null {
  const nested = path.join(installPath, 'ComfyUI')
  if (fs.existsSync(path.join(nested, 'main.py'))) return nested
  if (fs.existsSync(path.join(installPath, 'main.py'))) return installPath
  return null
}

/** Launch recipe for the host, or null when this install has no python / ComfyUI. */
export function resolveStudioCommand(installation: InstallationRecord): ComfyStudioCommand | null {
  const cmd = getActivePythonPath(installation)
  if (!cmd) return null
  const comfyuiDir = findComfyUIDir(installation.installPath)
  if (!comfyuiDir) return null
  return {
    cmd,
    args: [
      '-X',
      'utf8',
      '-m',
      'comfy_studio',
      '--comfyui-dir',
      comfyuiDir,
      '--request-timeout',
      String(STUDIO_REQUEST_TIMEOUT_MS / 1000),
      // Canvas tools need somebody to answer `canvas_call` (see
      // `comfyStudioCanvasRelay`); this shell is that somebody, so the extra
      // tool table is asked for here and nowhere else.
      '--canvas',
      // `review__ask_user` needs somebody to paint the question and carry the
      // answer back — the injected panel does both. Same deal: this shell asks
      // for that tool table, no other caller does.
      '--review'
    ],
    cwd: getBundledLibDir(),
    comfyuiDir
  }
}

export class ComfyStudioHost extends EventEmitter {
  private child: ChildProcessWithoutNullStreams | null = null
  private stdoutBuffer = ''
  private stderrBuffer = ''
  private nextId = 1
  private readonly pending = new Map<number, PendingRequest>()

  constructor(
    private readonly command: ComfyStudioCommand,
    private readonly options: ComfyStudioHostOptions = {}
  ) {
    super()
  }

  get running(): boolean {
    return this.child !== null
  }

  get comfyuiDir(): string {
    return this.command.comfyuiDir
  }

  /** Idempotent: a live child is left alone. */
  start(): void {
    if (this.child) return
    const spawnImpl = this.options.spawnImpl ?? spawn
    const child = spawnImpl(this.command.cmd, this.command.args, {
      cwd: this.command.cwd,
      env: { ...process.env, ...this.options.env },
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true
    }) as ChildProcessWithoutNullStreams
    this.child = child
    this.stdoutBuffer = ''
    this.stderrBuffer = ''

    child.stdout.setEncoding('utf8')
    child.stdout.on('data', (chunk: string) => this.consumeStdout(chunk))
    child.stderr.setEncoding('utf8')
    child.stderr.on('data', (chunk: string) => this.consumeStderr(chunk))
    child.on('error', (err: Error) => {
      // Spawn failures (missing interpreter, bad cwd) land here.
      this.child = null
      this.rejectAll(new ComfyStudioError(`comfy-studio 宿主启动失败: ${err.message}`))
    })
    child.on('exit', (code) => {
      this.child = null
      this.rejectAll(new ComfyStudioError(`comfy-studio 宿主进程已退出（code=${code ?? 'null'}）`))
      this.emit('exit', code)
    })
  }

  /** Close stdin so the host sees EOF and exits on its own; kill after a grace period. */
  stop(): void {
    const child = this.child
    if (!child) return
    this.child = null
    try {
      child.stdin.end()
    } catch {
      // Already gone; the fallback kill below is what matters.
    }
    const timer = setTimeout(() => {
      if (!child.killed) child.kill()
    }, STUDIO_STOP_GRACE_MS)
    timer.unref?.()
  }

  request<T = unknown>(method: string, params: unknown = {}): Promise<T> {
    const child = this.child
    if (!child || !child.stdin.writable) {
      return Promise.reject(new ComfyStudioError('comfy-studio 宿主没在运行：先 start()'))
    }
    const id = this.nextId++
    const timeoutMs = this.options.requestTimeoutMs ?? STUDIO_REQUEST_TIMEOUT_MS
    const promise = new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id)
        reject(new ComfyStudioError(`comfy-studio 请求 ${method} 超时（${timeoutMs}ms）`))
      }, timeoutMs)
      timer.unref?.()
      this.pending.set(id, {
        method,
        resolve: resolve as (value: unknown) => void,
        reject,
        timer
      })
    })
    child.stdin.write(`${JSON.stringify({ jsonrpc: '2.0', id, method, params })}\n`)
    return promise
  }

  private consumeStdout(chunk: string): void {
    this.stdoutBuffer += chunk
    let newline = this.stdoutBuffer.indexOf('\n')
    while (newline !== -1) {
      const line = this.stdoutBuffer.slice(0, newline).trim()
      this.stdoutBuffer = this.stdoutBuffer.slice(newline + 1)
      if (line !== '') this.handleLine(line)
      newline = this.stdoutBuffer.indexOf('\n')
    }
  }

  private consumeStderr(chunk: string): void {
    this.stderrBuffer += chunk
    let newline = this.stderrBuffer.indexOf('\n')
    while (newline !== -1) {
      const line = this.stderrBuffer.slice(0, newline).trim()
      this.stderrBuffer = this.stderrBuffer.slice(newline + 1)
      if (line !== '') this.log(`[comfy-studio] ${line}`)
      newline = this.stderrBuffer.indexOf('\n')
    }
  }

  private handleLine(line: string): void {
    let message: Record<string, unknown>
    try {
      const parsed: unknown = JSON.parse(line)
      if (!parsed || typeof parsed !== 'object') throw new Error('不是对象')
      message = parsed as Record<string, unknown>
    } catch (err) {
      this.log(`无法解析宿主输出: ${(err as Error).message}；原文: ${line.slice(0, 200)}`)
      return
    }

    const id = message.id
    if (typeof id === 'number') {
      const pending = this.pending.get(id)
      if (!pending) {
        this.log(`收到未知请求 id=${id} 的响应（可能已超时）`)
        return
      }
      this.pending.delete(id)
      clearTimeout(pending.timer)
      const error = message.error
      if (error && typeof error === 'object') {
        const { code, message: text } = error as { code?: unknown; message?: unknown }
        pending.reject(
          new ComfyStudioError(
            `${pending.method} 失败: ${typeof text === 'string' ? text : JSON.stringify(error)}`,
            typeof code === 'number' ? code : undefined
          )
        )
        return
      }
      pending.resolve(message.result)
      return
    }

    const method = message.method
    if (typeof method === 'string') {
      const params = (message.params ?? {}) as Record<string, unknown>
      this.emit('notification', { method, params } satisfies ComfyStudioNotification)
      return
    }
    this.log(`宿主输出里既没有 id 也没有 method: ${line.slice(0, 200)}`)
  }

  private rejectAll(error: Error): void {
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer)
      pending.reject(error)
    }
    this.pending.clear()
  }

  private log(line: string): void {
    if (this.options.log) this.options.log(line)
    else console.debug(line)
  }
}
