import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getComfyStudioChatContentScript } from './comfyStudioChatContentScript'

const BTN_ID = 'comfy-desktop-studio-chat-btn'
const DRAWER_ID = 'comfy-desktop-studio-chat'
const LOG_ID = 'comfy-desktop-studio-chat-log'
const STATUS_ID = 'comfy-desktop-studio-chat-status'
const INPUT_ID = 'comfy-desktop-studio-chat-input'
const SEND_ID = 'comfy-desktop-studio-chat-send'
const MODEL_ID = 'comfy-desktop-studio-chat-model'

interface StudioBridge {
  status: ReturnType<typeof vi.fn>
  start: ReturnType<typeof vi.fn>
  stop: ReturnType<typeof vi.fn>
  request: ReturnType<typeof vi.fn>
  onEvent: ReturnType<typeof vi.fn>
}

describe('getComfyStudioChatContentScript', () => {
  const script = getComfyStudioChatContentScript()
  let emit: (payload: unknown) => void = () => {}

  const setupDom = (): void => {
    document.body.innerHTML = `
      <nav data-testid="side-toolbar">
        <div class="top"></div>
        <div class="mt-auto">
          <button data-testid="help-center-button">?</button>
          <button data-testid="settings">gear</button>
        </div>
      </nav>
    `
  }

  /** Catalog the picker reads on open; a per-method stub can override it. */
  const catalog = (models: string[], current: string, error: string | null = null): unknown => ({
    ok: true,
    result: { current, models, source: error ? 'config' : 'endpoint', error }
  })

  type RequestStub = (method: string, params: unknown) => unknown

  const installBridge = (
    overrides: { status?: unknown; request?: unknown | RequestStub } = {}
  ): StudioBridge => {
    const bridge: StudioBridge = {
      status: vi.fn(() =>
        Promise.resolve(
          overrides.status ?? { installationId: 'i1', available: true, running: true }
        )
      ),
      start: vi.fn(() => Promise.resolve({ installationId: 'i1', available: true, running: true })),
      stop: vi.fn(() => Promise.resolve({ installationId: 'i1', available: true, running: false })),
      request: vi.fn((method: string, params: unknown) =>
        Promise.resolve(
          typeof overrides.request === 'function'
            ? (overrides.request as RequestStub)(method, params)
            : overrides.request ?? { ok: true, result: { text: '答案在此' } }
        )
      ),
      onEvent: vi.fn((callback: (payload: unknown) => void) => {
        emit = callback
        return vi.fn()
      })
    }
    Reflect.set(window, '__comfyDesktop2', { ComfyStudio: bridge })
    return bridge
  }

  const flush = async (): Promise<void> => {
    await vi.advanceTimersByTimeAsync(0)
  }

  const openPanel = async (): Promise<void> => {
    document.getElementById(BTN_ID)?.click()
    await flush()
  }

  const send = async (text: string): Promise<void> => {
    const input = document.getElementById(INPUT_ID) as HTMLTextAreaElement | null
    if (!input) throw new Error('Expected composer input')
    input.value = text
    document.getElementById(SEND_ID)?.click()
    await flush()
  }

  const rows = (kind: string): Element[] =>
    Array.from(document.querySelectorAll(`#${LOG_ID} [data-kind="${kind}"]`))

  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    const state = Reflect.get(window, '__comfyStudioChat') as
      | { observer?: MutationObserver; unsubscribe?: () => void }
      | undefined
    state?.observer?.disconnect()
    state?.unsubscribe?.()
    vi.clearAllTimers()
    vi.useRealTimers()
    document.body.innerHTML = ''
    Reflect.deleteProperty(window, '__comfyDesktop2')
    Reflect.deleteProperty(window, '__comfyStudioChat')
    emit = () => {}
  })

  it('returns a syntactically valid, self-contained IIFE', () => {
    expect(script.startsWith('(function () {')).toBe(true)
    expect(() => new Function(script)).not.toThrow()
  })

  it('injects nothing and keeps no state when the studio bridge is absent', () => {
    Reflect.set(window, '__comfyDesktop2', { Telemetry: { capture: vi.fn() } })
    setupDom()
    new Function(script)()
    expect(document.getElementById(BTN_ID), 'must bail without a studio bridge').toBeNull()
    expect(Reflect.get(window, '__comfyStudioChat')).toBeUndefined()
  })

  it('the re-entry guard stops a second run', () => {
    installBridge()
    setupDom()
    new Function(script)()
    document.getElementById(BTN_ID)?.remove()
    new Function(script)()
    expect(document.getElementById(BTN_ID)).toBeNull()
  })

  it('injects the sparkles button into the bottom cluster, above the help icon', () => {
    installBridge()
    setupDom()
    new Function(script)()

    const btn = document.getElementById(BTN_ID)
    const help = document.querySelector('[data-testid="help-center-button"]')
    expect(btn).not.toBeNull()
    if (!btn || !help) throw new Error('Expected button and help icon')
    expect(btn.parentElement).toBe(help.parentElement)
    expect(
      btn.compareDocumentPosition(help) & Node.DOCUMENT_POSITION_FOLLOWING,
      'ordered before help'
    ).toBeTruthy()
    expect(btn.querySelector('.icon-\\[lucide--sparkles\\]')).not.toBeNull()
  })

  it('subscribes to host events and can unsubscribe', () => {
    const bridge = installBridge()
    setupDom()
    new Function(script)()
    expect(bridge.onEvent).toHaveBeenCalledOnce()
    const state = Reflect.get(window, '__comfyStudioChat') as { unsubscribe?: () => void }
    expect(typeof state.unsubscribe).toBe('function')
  })

  it('opens the drawer on click and reports host status', async () => {
    const bridge = installBridge()
    setupDom()
    new Function(script)()
    expect(document.getElementById(DRAWER_ID), 'not built before first open').toBeNull()

    await openPanel()

    expect(document.getElementById(DRAWER_ID)?.style.display).toBe('flex')
    expect(bridge.status).toHaveBeenCalledOnce()
    expect(document.getElementById(STATUS_ID)?.textContent).toContain('运行中')
  })

  it('toggles the drawer shut on a second click', async () => {
    installBridge()
    setupDom()
    new Function(script)()
    await openPanel()
    document.getElementById(BTN_ID)?.click()
    await flush()
    expect(document.getElementById(DRAWER_ID)?.style.display).toBe('none')
  })

  it('sends a turn through the host and paints the answer', async () => {
    const bridge = installBridge()
    setupDom()
    new Function(script)()
    await openPanel()

    await send('帮我把这张图放大两倍')

    expect(bridge.request).toHaveBeenCalledWith('agent/chat', { text: '帮我把这张图放大两倍' })
    expect(rows('user').map((r) => r.textContent)).toEqual(['帮我把这张图放大两倍'])
    expect(rows('agent').map((r) => r.textContent)).toEqual(['答案在此'])
    const input = document.getElementById(INPUT_ID) as HTMLTextAreaElement
    expect(input.value, 'composer is cleared after sending').toBe('')
    expect((document.getElementById(SEND_ID) as HTMLButtonElement).disabled).toBe(false)
  })

  it('paints assistant/tool events of the running turn but not the duplicate final', async () => {
    installBridge()
    setupDom()
    new Function(script)()
    await openPanel()

    const input = document.getElementById(INPUT_ID) as HTMLTextAreaElement
    input.value = '跑个 skill'
    document.getElementById(SEND_ID)?.click() // 不 await：先让这一轮处于在飞行中

    emit({
      params: { type: 'assistant', text: '先查一下可用的 skill' }
    })
    emit({
      params: { type: 'tool_call', name: 'comfy-studio__comfy_list_skills', arguments: {} }
    })
    emit({
      params: { type: 'tool_result', name: 'comfy-studio__comfy_list_skills', text: '[{...}]' }
    })
    emit({ params: { type: 'final', text: '答案在此' } })

    await flush()

    expect(rows('agent').map((r) => r.textContent)).toEqual(['先查一下可用的 skill', '答案在此'])
    const toolRows = rows('tool').map((r) => r.textContent ?? '')
    expect(toolRows[0]).toContain('comfy-studio__comfy_list_skills')
    expect(toolRows[1]).toContain('←')
  })

  it('ignores host events when no turn is in flight', async () => {
    installBridge()
    setupDom()
    new Function(script)()
    await openPanel()

    emit({ params: { type: 'tool_call', name: 'x', arguments: {} } })

    expect(rows('tool')).toHaveLength(0)
  })

  it('shows an error row when the host reports a failed turn', async () => {
    installBridge({ request: { ok: false, error: { code: -32603, message: '模型没配' } } })
    setupDom()
    new Function(script)()
    await openPanel()

    await send('你好')

    expect(rows('error').map((r) => r.textContent)).toEqual(['失败: 模型没配'])
    expect(document.getElementById(STATUS_ID)?.textContent).toContain('失败')
  })

  it('disables sending while the install cannot host the studio', async () => {
    installBridge({
      status: { installationId: 'i1', available: false, running: false, error: '没有 python' }
    })
    setupDom()
    new Function(script)()
    await openPanel()

    expect(document.getElementById(STATUS_ID)?.textContent).toBe('没有 python')
    expect((document.getElementById(SEND_ID) as HTMLButtonElement).disabled).toBe(true)
  })

  it('stops the host from the drawer header', async () => {
    const bridge = installBridge()
    setupDom()
    new Function(script)()
    await openPanel()

    const stop = Array.from(document.querySelectorAll('button')).find(
      (b) => b.textContent === '停止宿主'
    )
    if (!stop) throw new Error('Expected stop button')
    stop.click()
    await flush()

    expect(bridge.stop).toHaveBeenCalledOnce()
  })

  it('re-injects via the observer when the toolbar re-renders the button away', async () => {
    installBridge()
    setupDom()
    new Function(script)()
    expect(document.getElementById(BTN_ID)).not.toBeNull()

    document.getElementById(BTN_ID)?.remove()
    document.querySelector('.mt-auto')?.appendChild(document.createElement('span'))
    await flush()

    expect(document.getElementById(BTN_ID)).not.toBeNull()
  })

  it('memoizes the assembled script', () => {
    expect(getComfyStudioChatContentScript()).toBe(script)
  })

  it('fills the model picker from the host catalog when the drawer opens', async () => {
    const request = vi.fn((method: string) =>
      method === 'agent/models'
        ? catalog(['a:3b', 'b:7b'], 'b:7b')
        : { ok: true, result: { text: '答案在此' } }
    )
    installBridge({ request })
    setupDom()
    new Function(script)()

    const select = document.getElementById(MODEL_ID) as HTMLSelectElement
    expect(select, 'picker is part of the drawer').toBeNull()

    await openPanel()

    expect(request.mock.calls[0]?.[0]).toBe('agent/models')
    const picker = document.getElementById(MODEL_ID) as HTMLSelectElement
    expect(Array.from(picker.options).map((o) => o.value)).toEqual(['a:3b', 'b:7b'])
    expect(picker.value, 'current model is preselected').toBe('b:7b')
    expect(picker.disabled).toBe(false)
  })

  it('switches the model through the host and reports it in the status line', async () => {
    const request = vi.fn((method: string) =>
      method === 'agent/models'
        ? catalog(['a:3b', 'b:7b'], 'a:3b')
        : { ok: true, result: { model: 'b:7b', changed: true, applied: ['default'], skipped: [] } }
    )
    installBridge({ request })
    setupDom()
    new Function(script)()
    await openPanel()

    const picker = document.getElementById(MODEL_ID) as HTMLSelectElement
    picker.value = 'b:7b'
    picker.dispatchEvent(new Event('change'))
    await flush()

    expect(request).toHaveBeenCalledWith('agent/model', { model: 'b:7b' })
    expect(document.getElementById(STATUS_ID)?.textContent).toContain('b:7b')
    expect(picker.value).toBe('b:7b')
    expect(picker.disabled).toBe(false)
    expect(rows('error'), 'a successful switch must not paint an error').toHaveLength(0)
  })

  it('rolls the picker back when the host rejects the switch', async () => {
    const request = vi.fn((method: string) =>
      method === 'agent/models'
        ? catalog(['a:3b', 'b:7b'], 'a:3b')
        : { ok: false, error: { code: -32602, message: '没有这个模型' } }
    )
    installBridge({ request })
    setupDom()
    new Function(script)()
    await openPanel()

    const picker = document.getElementById(MODEL_ID) as HTMLSelectElement
    picker.value = 'b:7b'
    picker.dispatchEvent(new Event('change'))
    await flush()

    expect(picker.value, 'selection falls back to the model actually in use').toBe('a:3b')
    expect(rows('error').map((r) => r.textContent)).toEqual(['切换模型失败: 没有这个模型'])
    expect(picker.disabled).toBe(false)
  })

  it('says why only the configured model is offered', async () => {
    const request = vi.fn(() => ({
      ok: true,
      result: {
        current: 'only:1',
        models: ['only:1'],
        source: 'config',
        error: '连不上 http://127.0.0.1:9/v1/models: boom'
      }
    }))
    installBridge({ request })
    setupDom()
    new Function(script)()
    await openPanel()

    const picker = document.getElementById(MODEL_ID) as HTMLSelectElement
    expect(Array.from(picker.options).map((o) => o.value)).toEqual(['only:1'])
    expect(picker.title).toContain('服务端没给模型列表')
    expect(picker.title).toContain('boom')
  })

  it('leaves the picker disabled when the catalog cannot be read', async () => {
    installBridge({ request: { ok: false, error: { message: '宿主没在运行' } } })
    setupDom()
    new Function(script)()
    await openPanel()

    const picker = document.getElementById(MODEL_ID) as HTMLSelectElement
    expect(picker.disabled).toBe(true)
    expect(picker.title).toContain('宿主没在运行')
  })

  it('locks the picker while a turn is in flight', async () => {
    const request = vi.fn((method: string) =>
      method === 'agent/models' ? catalog(['a:3b'], 'a:3b') : { ok: true, result: { text: '答案在此' } }
    )
    installBridge({ request })
    setupDom()
    new Function(script)()
    await openPanel()

    const picker = document.getElementById(MODEL_ID) as HTMLSelectElement
    expect(picker.disabled).toBe(false)

    const input = document.getElementById(INPUT_ID) as HTMLTextAreaElement
    input.value = '跑个 skill'
    document.getElementById(SEND_ID)?.click() // 不 await：这一轮在飞行中
    expect(picker.disabled, 'switching mid-turn would cut the turn off').toBe(true)

    await flush()
    expect(picker.disabled).toBe(false)
  })

})
