import { app, ipcMain } from 'electron'
import type { IpcMainInvokeEvent } from 'electron'
import * as installations from '../../installations'
import { findInstallationIdByComfySender, getEntryByInstallationId } from '../../host/registry'
import { ComfyStudioError, ComfyStudioHost, resolveStudioCommand } from '../comfyStudioHost'
import type { ComfyStudioNotification } from '../comfyStudioHost'
import { isCanvasCall, relayCanvasCall } from '../comfyStudioCanvasRelay'
import { _broadcastToRenderer } from './broadcast'

/**
 * IPC for the desktop-side comfy-studio host (`lib/comfy_studio`).
 *
 * One host process per installation, started lazily on the first request so a
 * user who never opens the studio chat pays for nothing. The renderer talks to
 * it through a single generic `comfy-studio:request` proxy rather than one
 * channel per host method: the host's own protocol is the API here, and
 * mirroring its nine methods as nine channels would only add drift.
 *
 * `agent/event` notifications from the host are rebroadcast on
 * `comfy-studio:event` (carrying the installationId) so a panel can paint
 * tool calls while the agent loop is still running.
 *
 * A `canvas_call` event is the one notification that also needs an answer: the
 * graph lives in the page, not in the host, so it is run in that installation's
 * comfyView and the result goes back over `agent/canvas_result`
 * (see `comfyStudioCanvasRelay`).
 *
 * Callers come in two shapes, same as the logs/terminal IPC:
 *   - the desktop renderer passes its installationId explicitly;
 *   - the injected canvas chat does not know its installationId, so we resolve
 *     it from the sender via the comfyView registry.
 */

export interface ComfyStudioStatus {
  installationId: string | null
  /** False when this install has no usable python/ComfyUI checkout. */
  available: boolean
  running: boolean
  comfyuiDir?: string
  error?: string
}

export type ComfyStudioRequestResult =
  | { ok: true; result: unknown }
  | { ok: false; error: { code?: number; message: string } }

const hosts = new Map<string, ComfyStudioHost>()

/** Creation in flight, keyed like `hosts`.
 *
 *  Building a host awaits `installations.get`, so a bare `hosts.get` check is not
 *  enough to make `hostFor` a get-or-create: every caller that arrives during that
 *  await sees an empty map and builds its own process. A panel opening fires
 *  several requests at once, and one sighting left eight hosts under a single
 *  installation, spawned 41ms apart. Worse, they all `hosts.set` the same key —
 *  the losers are unreachable, so `stopAllComfyStudioHosts` cannot stop them and
 *  they outlive the app. This map is what makes the concurrent callers share one
 *  creation instead of racing. */
const hostsStarting = new Map<string, Promise<ComfyStudioHost>>()

function resolveInstallationId(
  event: IpcMainInvokeEvent,
  explicit: string | null | undefined
): string | null {
  if (explicit) return explicit
  return findInstallationIdByComfySender(event.sender)
}

function statusWithoutHost(installationId: string | null, error: string): ComfyStudioStatus {
  return { installationId, available: false, running: false, error }
}

async function statusFor(installationId: string | null): Promise<ComfyStudioStatus> {
  if (!installationId) return statusWithoutHost(null, '拿不到 installationId')
  const host = hosts.get(installationId)
  if (host) {
    return {
      installationId,
      available: true,
      running: host.running,
      comfyuiDir: host.comfyuiDir
    }
  }
  const installation = await installations.get(installationId)
  if (!installation) return statusWithoutHost(installationId, '没有这条安装记录')
  const command = resolveStudioCommand(installation)
  if (!command) {
    return statusWithoutHost(
      installationId,
      '这个安装没有可用的 venv python 或 ComfyUI 检出；先把 ComfyUI 装好'
    )
  }
  return { installationId, available: true, running: false, comfyuiDir: command.comfyuiDir }
}

/** Get-or-create the host for an installation. Does not start the process.
 *
 *  Concurrent callers share one creation: see `hostsStarting`. */
async function hostFor(installationId: string): Promise<ComfyStudioHost> {
  const existing = hosts.get(installationId)
  if (existing) return existing

  const starting = hostsStarting.get(installationId)
  if (starting) return starting

  const pending = createHost(installationId)
  hostsStarting.set(installationId, pending)
  try {
    return await pending
  } finally {
    hostsStarting.delete(installationId)
  }
}

/** Build the host for an installation. Callers go through `hostFor`, which is what
 *  keeps two of these from landing under the same key. */
async function createHost(installationId: string): Promise<ComfyStudioHost> {
  const installation = await installations.get(installationId)
  if (!installation) throw new ComfyStudioError(`找不到安装记录 ${installationId}`)
  const command = resolveStudioCommand(installation)
  if (!command) {
    throw new ComfyStudioError('这个安装没有可用的 venv python 或 ComfyUI 检出；先把 ComfyUI 装好')
  }

  const host = new ComfyStudioHost(command)
  host.on('notification', (message: ComfyStudioNotification) => {
    _broadcastToRenderer('comfy-studio:event', { installationId, ...message })
    if (!isCanvasCall(message.method, message.params)) return
    // Fire-and-forget: the notification stream must not stall on one op.
    const view = getEntryByInstallationId(installationId)?.comfyView ?? null
    void relayCanvasCall(host, view ? view.webContents : null, message.params).catch(() => {})
  })
  host.on('exit', () => {
    hosts.delete(installationId)
  })
  hosts.set(installationId, host)
  return host
}

/** Stop every host (app quit, or tests). */
export function stopAllComfyStudioHosts(): void {
  for (const host of hosts.values()) host.stop()
  hosts.clear()
}

export function registerComfyStudioHandlers(): void {
  ipcMain.handle(
    'comfy-studio:status',
    (event, installationId?: string | null): Promise<ComfyStudioStatus> =>
      statusFor(resolveInstallationId(event, installationId))
  )

  ipcMain.handle(
    'comfy-studio:start',
    async (event, installationId?: string | null): Promise<ComfyStudioStatus> => {
      const id = resolveInstallationId(event, installationId)
      if (!id) return statusWithoutHost(null, '拿不到 installationId')
      try {
        const host = await hostFor(id)
        host.start()
      } catch (err) {
        return statusWithoutHost(id, (err as Error).message)
      }
      return statusFor(id)
    }
  )

  ipcMain.handle(
    'comfy-studio:stop',
    async (event, installationId?: string | null): Promise<ComfyStudioStatus> => {
      const id = resolveInstallationId(event, installationId)
      if (!id) return statusWithoutHost(null, '拿不到 installationId')
      hosts.get(id)?.stop()
      return statusFor(id)
    }
  )

  ipcMain.handle(
    'comfy-studio:request',
    async (
      event,
      payload?: { method?: string; params?: unknown; installationId?: string | null }
    ): Promise<ComfyStudioRequestResult> => {
      const id = resolveInstallationId(event, payload?.installationId)
      if (!id) return { ok: false, error: { message: '拿不到 installationId' } }
      const method = payload?.method
      if (typeof method !== 'string' || method === '') {
        return { ok: false, error: { message: '缺少 method' } }
      }
      try {
        const host = await hostFor(id)
        host.start() // no-op when already up
        const result = await host.request(method, payload?.params ?? {})
        return { ok: true, result }
      } catch (err) {
        const failure = err as ComfyStudioError
        return {
          ok: false,
          error: { code: failure.code, message: failure.message || String(err) }
        }
      }
    }
  )

  app.on('will-quit', stopAllComfyStudioHosts)
}
