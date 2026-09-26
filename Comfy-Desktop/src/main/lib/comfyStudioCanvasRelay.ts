/**
 * Reach-back for comfy-studio canvas work.
 *
 * The host's `canvas__*` tools run in the python process, but the graph they act
 * on only exists in the hosted ComfyUI page. So a `canvas_call` notification is
 * answered here: run the op in that installation's comfyView, then hand the
 * answer back over `agent/canvas_result` — the host is awaiting a future keyed by
 * `call_id` (see `lib/comfy_studio/canvas.py`).
 *
 * No Electron imports below on purpose: a fake page and a fake host are enough to
 * test the whole route.
 */

export interface CanvasAnswer {
  ok: boolean
  result?: unknown
  error?: string
}

/** The slice of `WebContents` this needs. */
export interface CanvasPage {
  isDestroyed(): boolean
  executeJavaScript(code: string, userGesture?: boolean): Promise<unknown>
}

/** The slice of `ComfyStudioHost` this needs. */
export interface CanvasHost {
  request(method: string, params: unknown): Promise<unknown>
}

/**
 * The op is run by the chat script already injected in that page
 * (`window.__comfyStudioChat.canvasCall`). A page without it answers `ok: false`
 * rather than throwing, so the host gets a readable reason either way.
 */
export function canvasCallScript(op: string, args: unknown): string {
  return (
    `(function () {\n` +
    `  var panel = window.__comfyStudioChat;\n` +
    `  if (!panel || typeof panel.canvasCall !== 'function') {\n` +
    `    return { ok: false, error: '这个页面里没有 comfy-studio 对话脚本：画布通道不在' };\n` +
    `  }\n` +
    `  return panel.canvasCall(${JSON.stringify(op)}, ${JSON.stringify(args ?? {})});\n` +
    `})()`
  )
}

export async function askCanvasPage(
  page: CanvasPage | null,
  op: string,
  args: unknown
): Promise<CanvasAnswer> {
  if (!page || page.isDestroyed()) {
    return { ok: false, error: '这个安装的画布窗口没开，读不到图' }
  }
  try {
    const answer = await page.executeJavaScript(canvasCallScript(op, args))
    if (!answer || typeof answer !== 'object') {
      return { ok: false, error: '画布页面没有回话' }
    }
    return answer as CanvasAnswer
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    return { ok: false, error: `画布动作没能执行：${message}` }
  }
}

export interface CanvasRelayResult {
  /** True when the host took it; false means the turn already stopped waiting. */
  delivered: boolean
  answer: CanvasAnswer
}

/**
 * Answer one `canvas_call`. Never throws: the host is waiting on a future, and a
 * missing window is a normal answer, not an error in the notification stream.
 */
export async function relayCanvasCall(
  host: CanvasHost,
  page: CanvasPage | null,
  params: Record<string, unknown>
): Promise<CanvasRelayResult> {
  const callId = typeof params.call_id === 'string' ? params.call_id : ''
  const op = typeof params.op === 'string' ? params.op : ''
  const args = (params.args ?? {}) as Record<string, unknown>
  if (!callId || !op) {
    return { delivered: false, answer: { ok: false, error: '画布动作缺少 call_id 或 op' } }
  }

  const answer = await askCanvasPage(page, op, args)
  try {
    const reply = await host.request('agent/canvas_result', {
      call_id: callId,
      ok: answer.ok,
      result: answer.result ?? null,
      error: answer.error ?? null
    })
    const delivered =
      !!reply && typeof reply === 'object' && (reply as { delivered?: unknown }).delivered === true
    return { delivered, answer }
  } catch {
    // Host gone (panel closed, app quitting): nobody is waiting any more.
    return { delivered: false, answer }
  }
}

/** True when a host notification is a canvas call this module answers. */
export function isCanvasCall(method: string, params: Record<string, unknown>): boolean {
  return method === 'agent/event' && params.type === 'canvas_call'
}
