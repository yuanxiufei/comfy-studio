import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getComfyStudioChatContentScript } from './comfyStudioChatContentScript'

const BTN_ID = 'comfy-desktop-studio-chat-btn'
const DRAWER_ID = 'comfy-desktop-studio-chat'
const LOG_ID = 'comfy-desktop-studio-chat-log'
const STATUS_ID = 'comfy-desktop-studio-chat-status'
const INPUT_ID = 'comfy-desktop-studio-chat-input'
const SEND_ID = 'comfy-desktop-studio-chat-send'
const STOP_ID = 'comfy-desktop-studio-chat-stop'
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
    Reflect.deleteProperty(window, 'comfyAPI')
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
    expect(rows('assistant').map((r) => r.textContent)).toEqual(['答案在此'])
    const input = document.getElementById(INPUT_ID) as HTMLTextAreaElement
    expect(input.value, 'composer is cleared after sending').toBe('')
    expect((document.getElementById(SEND_ID) as HTMLButtonElement).disabled).toBe(false)
  })

  it('marks the turn in flight and paints the final answer as the final node', async () => {
    installBridge()
    setupDom()
    new Function(script)()
    await openPanel()

    const input = document.getElementById(INPUT_ID) as HTMLTextAreaElement
    input.value = '跑个 skill'
    document.getElementById(SEND_ID)?.click() // 不 await：先让这一轮处于在飞行中

    expect(rows('pending'), 'a turn in flight says where the answer will land').toHaveLength(1)

    emit({ params: { session_id: 'default', type: 'assistant', text: '先查一下可用的 skill' } })
    emit({ params: { session_id: 'default', type: 'final', text: '答案在此' } })

    await flush()

    expect(rows('pending'), 'the pending row goes away when the turn settles').toHaveLength(0)
    // final 事件本身不画：同一段文本由请求结果带回，画两遍就重复了
    expect(rows('assistant').map((r) => r.textContent)).toEqual(['先查一下可用的 skill', '答案在此'])
    expect(rows('assistant')[0]?.getAttribute('data-variant')).toBe('intermediate')
    expect(rows('assistant')[1]?.getAttribute('data-variant')).toBe('final')
  })

  it('pairs a tool result with the card its call opened', async () => {
    installBridge()
    setupDom()
    new Function(script)()
    await openPanel()

    const input = document.getElementById(INPUT_ID) as HTMLTextAreaElement
    input.value = '跑个 skill'
    document.getElementById(SEND_ID)?.click() // 不 await：这一轮在飞行中

    emit({
      params: {
        session_id: 'default',
        type: 'tool_call',
        id: 'call_1',
        name: 'comfy-studio__comfy_list_skills',
        arguments: { limit: 5 }
      }
    })

    expect(rows('tool'), 'one card per call').toHaveLength(1)
    const card = rows('tool')[0]
    if (!card) throw new Error('Expected a tool card')
    expect(card.getAttribute('data-state'), 'a call with no result yet is running').toBe('running')
    expect(card.querySelector('.cs-tool-server')?.textContent).toBe('comfy-studio')
    expect(card.querySelector('.cs-tool-name')?.textContent).toBe('comfy_list_skills')
    expect(card.querySelector('.cs-block')?.textContent, 'arguments are shown').toContain('"limit": 5')

    emit({
      params: {
        session_id: 'default',
        type: 'tool_result',
        id: 'call_1',
        name: 'comfy-studio__comfy_list_skills',
        text: '[{...}]'
      }
    })

    expect(rows('tool'), 'the result updates that card instead of adding a row').toHaveLength(1)
    expect(card.getAttribute('data-state')).toBe('done')
    expect(card.querySelector('.cs-tool-state')?.textContent).toBe('完成')
    expect(card.textContent).toContain('[{...}]')
  })

  it('flags a failed tool result, and keeps one whose call never arrived', async () => {
    installBridge()
    setupDom()
    new Function(script)()
    await openPanel()

    const input = document.getElementById(INPUT_ID) as HTMLTextAreaElement
    input.value = '跑个 skill'
    document.getElementById(SEND_ID)?.click() // 不 await：这一轮在飞行中

    emit({ params: { session_id: 'default', type: 'tool_call', id: 'call_1', name: 'srv__run', arguments: {} } })
    // 宿主把 isError 的结果标成 "ERROR: ..." 文本喂回来（mcp/result.py 的 tool_text）
    emit({
      params: { session_id: 'default', type: 'tool_result', id: 'call_1', name: 'srv__run', text: 'ERROR: 显存不够' }
    })

    expect(rows('tool')[0]?.getAttribute('data-state')).toBe('error')
    expect(rows('tool')[0]?.querySelector('.cs-tool-state')?.textContent).toBe('失败')

    emit({ params: { session_id: 'default', type: 'tool_result', id: 'call_9', name: 'srv__run', text: '结果' } })

    const cards = rows('tool')
    expect(cards, 'a result without its call must not be dropped').toHaveLength(2)
    expect(cards[1]?.getAttribute('data-orphan')).toBe('1')
    expect(cards[1]?.textContent).toContain('没等到调用事件')
  })

  it('folds a long tool result behind a button instead of losing it', async () => {
    installBridge()
    setupDom()
    new Function(script)()
    await openPanel()

    const input = document.getElementById(INPUT_ID) as HTMLTextAreaElement
    input.value = '跑个 skill'
    document.getElementById(SEND_ID)?.click() // 不 await：这一轮在飞行中

    const long = 'x'.repeat(700)
    emit({ params: { session_id: 'default', type: 'tool_call', id: 'call_1', name: 'srv__run', arguments: {} } })
    emit({ params: { session_id: 'default', type: 'tool_result', id: 'call_1', name: 'srv__run', text: long } })

    const card = rows('tool')[0]
    if (!card) throw new Error('Expected the tool card')
    const blocks = (): string[] =>
      Array.from(card.querySelectorAll('.cs-block')).map((b) => b.textContent ?? '')
    const more = card.querySelector('.cs-block-more') as HTMLButtonElement | null
    expect(more?.textContent, 'the button says how much is hidden').toContain('700')
    expect(blocks()[blocks().length - 1]?.length, 'the card shows a folded copy').toBeLessThan(
      long.length
    )

    more?.click()

    expect(blocks()[blocks().length - 1], 'expanding shows the whole text').toBe(long)
    expect(card.querySelector('.cs-block-more')).toBeNull()
  })

  it('ignores events belonging to another session', async () => {
    installBridge()
    setupDom()
    new Function(script)()
    await openPanel()

    const input = document.getElementById(INPUT_ID) as HTMLTextAreaElement
    input.value = '你好'
    document.getElementById(SEND_ID)?.click() // 不 await：这一轮在飞行中

    emit({ params: { session_id: 'someone-else', type: 'assistant', text: '别的会话的话' } })

    expect(rows('assistant'), 'another session is not this drawer turn').toHaveLength(0)
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

    expect(rows('error').map((r) => r.textContent)).toEqual(['失败: 模型没配（错误码 -32603）'])
    expect(rows('error')[0]?.getAttribute('data-error-code')).toBe('-32603')
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

  it('stops a turn from the composer and paints 已停止 instead of an empty answer', async () => {
    let settleChat: (value: unknown) => void = () => {}
    const request = vi.fn((method: string) => {
      if (method === 'agent/models') return catalog(['a:3b'], 'a:3b')
      if (method === 'agent/cancel') {
        return { ok: true, result: { session_id: 'default', cancelled: true } }
      }
      return new Promise((resolve) => {
        settleChat = resolve
      })
    })
    installBridge({ request })
    setupDom()
    new Function(script)()
    await openPanel()

    const stop = document.getElementById(STOP_ID) as HTMLButtonElement
    expect(stop.style.display, 'nothing to stop before a turn starts').toBe('none')

    const input = document.getElementById(INPUT_ID) as HTMLTextAreaElement
    input.value = '跑个 skill'
    document.getElementById(SEND_ID)?.click() // 不 await：这一轮在飞行中
    expect(stop.style.display, 'the stop button shows up with the turn').not.toBe('none')

    stop.click()
    await flush()

    expect(request).toHaveBeenCalledWith('agent/cancel', { session_id: 'default' })

    // 停下之后宿主仍把 agent/chat 正常答完：结果带 cancelled:true
    settleChat({ ok: true, result: { session_id: 'default', text: '', cancelled: true, reason: '用户取消' } })
    await flush()

    expect(rows('stopped').map((r) => r.textContent)).toEqual(['已停止'])
    expect(rows('stopped')[0]?.getAttribute('title')).toContain('用户取消')
    expect(rows('assistant'), 'a stopped turn has no answer to paint').toHaveLength(0)
    expect(rows('error'), 'stopping is not a failure').toHaveLength(0)
    expect(rows('pending'), 'the turn still settles').toHaveLength(0)
    expect(stop.style.display, 'the turn is over, so no stop button').toBe('none')
    expect((document.getElementById(SEND_ID) as HTMLButtonElement).disabled).toBe(false)
    expect(document.getElementById(STATUS_ID)?.textContent).toContain('已停止')
  })

  it('says so when the host will not stop the turn, and keeps the button usable', async () => {
    const request = vi.fn((method: string) => {
      if (method === 'agent/models') return catalog(['a:3b'], 'a:3b')
      if (method === 'agent/cancel') return { ok: false, error: { message: '宿主没在运行' } }
      return new Promise(() => {}) // 这一轮一直挂着：取消失败就该看得出来
    })
    installBridge({ request })
    setupDom()
    new Function(script)()
    await openPanel()

    const input = document.getElementById(INPUT_ID) as HTMLTextAreaElement
    input.value = '跑个 skill'
    document.getElementById(SEND_ID)?.click() // 不 await：这一轮在飞行中

    const stop = document.getElementById(STOP_ID) as HTMLButtonElement
    stop.click()
    await flush()

    expect(rows('error').map((r) => r.textContent)).toEqual(['取消失败: 宿主没在运行'])
    expect(document.getElementById(STATUS_ID)?.textContent).toContain('还在跑')
    expect(stop.disabled, 'a failed cancel must not leave the button stuck').toBe(false)
    expect(stop.style.display, 'the turn is still in flight').not.toBe('none')
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
    expect(rows('error').map((r) => r.textContent)).toEqual([
      '切换模型失败: 没有这个模型（错误码 -32602）'
    ])
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

  // ---- 画布通道：桌面壳用 executeJavaScript 调 STATE.canvasCall -------------

  interface FakeApp {
    rootGraph: { serialize: () => unknown }
    loadGraphData: ReturnType<typeof vi.fn>
  }

  /** The ComfyUI frontend's own global, faked: `window.comfyAPI.app.app`. */
  const installCanvasApp = (graph?: unknown): FakeApp => {
    const app: FakeApp = {
      rootGraph: { serialize: () => graph ?? { nodes: [], links: [] } },
      loadGraphData: vi.fn(() => Promise.resolve())
    }
    Reflect.set(window, 'comfyAPI', { app: { app } })
    return app
  }

  interface CanvasAnswer {
    ok: boolean
    result?: unknown
    error?: string
  }

  type CanvasCall = (op: string, args: unknown) => Promise<CanvasAnswer>

  const canvasCall = (): CanvasCall => {
    const state = Reflect.get(window, '__comfyStudioChat') as
      | { canvasCall?: CanvasCall }
      | undefined
    if (!state?.canvasCall) throw new Error('Expected the panel to expose canvasCall')
    return state.canvasCall
  }

  const boot = (): void => {
    installBridge()
    setupDom()
    new Function(script)()
  }

  it('summarises the live graph for the host', async () => {
    installCanvasApp({
      nodes: [
        { id: 4, type: 'CheckpointLoaderSimple', widgets_values: ['sd_xl.safetensors'] },
        { id: 7, type: 'KSampler', title: '采样' }
      ],
      links: [[1, 4, 0, 7, 0, 'MODEL']],
      extra: { ds: { filename: 'demo' } }
    })
    boot()

    const shot = (await canvasCall()('snapshot', {})).result as {
      node_count: number
      link_count: number
      nodes: unknown[]
      links: unknown[]
      workflow_name?: string
      truncated: boolean
    }
    expect(shot.node_count).toBe(2)
    expect(shot.link_count).toBe(1)
    expect(shot.workflow_name).toBe('demo')
    expect(shot.truncated).toBe(false)
    expect(shot.links).toEqual([{ from: 4, from_slot: 0, to: 7, to_slot: 0 }])
    // Widget values cost tokens: not sent unless the host asks for them.
    expect(shot.nodes[0]).toEqual({ id: 4, type: 'CheckpointLoaderSimple' })
    expect(shot.nodes[1]).toEqual({ id: 7, type: 'KSampler', title: '采样' })
  })

  it('reads node parameters when the host asks for them', async () => {
    installCanvasApp({ nodes: [{ id: 4, type: 'KSampler', widgets_values: [20, 'euler'] }] })
    boot()

    const shot = (await canvasCall()('snapshot', { include_widgets: true })).result as {
      nodes: { widgets?: string }[]
    }
    expect(shot.nodes[0]?.widgets).toBe('[20,"euler"]')
  })

  it('says so when the frontend exposes no graph to read', async () => {
    boot()

    const answer = await canvasCall()('snapshot', {})
    expect(answer.ok).toBe(false)
    expect(answer.error).toContain('读不到画布')
  })

  it('loads a workflow into the canvas through the frontend API', async () => {
    const app = installCanvasApp({ nodes: [{ id: 1, type: 'KSampler' }], links: [] })
    boot()

    const answer = await canvasCall()('load_workflow', {
      graph: { nodes: [], links: [] },
      name: '我的图'
    })
    expect(answer.ok).toBe(true)
    expect(app.loadGraphData).toHaveBeenCalledWith({ nodes: [], links: [] }, true, true, '我的图')
    expect(answer.result).toEqual({ loaded: true, node_count: 1 })
  })

  it('rejects a graph that is not a workflow object', async () => {
    const app = installCanvasApp()
    boot()

    const answer = await canvasCall()('load_workflow', { graph: 'nope' })
    expect(answer.ok).toBe(false)
    expect(answer.error).toContain('graph')
    expect(app.loadGraphData).not.toHaveBeenCalled()
  })

  it('refuses an unknown canvas op instead of doing nothing', async () => {
    installCanvasApp()
    boot()

    const answer = await canvasCall()('teleport', {})
    expect(answer.ok).toBe(false)
    expect(answer.error).toContain('不认识的画布动作')
  })

})
