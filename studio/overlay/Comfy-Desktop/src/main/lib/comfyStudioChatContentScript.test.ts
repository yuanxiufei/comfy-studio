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

  describe('coming back to an older conversation', () => {
    /** 只有 `agent/history` 走自己的桩：开抽屉时面板还会问模型目录，那些保持默认。 */
    const archive = (result: unknown): RequestStub => (method) =>
      method === 'agent/history' ? result : { ok: true, result: { text: '答案在此' } }

    const archived = (result: Record<string, unknown>): unknown => ({
      ok: true,
      result: {
        session_id: 'default',
        source: 'store',
        messages: 0,
        dropped: 0,
        saved_at: '2026-09-26T10:00:00+00:00',
        entries: [],
        ...result
      }
    })

    it('an empty drawer repaints the archived conversation when it opens', async () => {
      const bridge = installBridge({
        request: archive(
          archived({
            messages: 4,
            entries: [
              { type: 'user', text: '帮我把这张图放大两倍' },
              { type: 'assistant', text: '先查一下可用的 skill', variant: 'intermediate' },
              { type: 'tool_call', id: 'call_1', name: 'fake__do_it', arguments: { scale: 2 } },
              { type: 'tool_result', id: 'call_1', name: 'fake__do_it', text: '{"ok": true}' },
              { type: 'assistant', text: '已经好了', variant: 'final' }
            ]
          })
        )
      })
      setupDom()
      new Function(script)()
      await openPanel()

      expect(bridge.request).toHaveBeenCalledWith('agent/history', { session_id: 'default' })
      const log = document.getElementById(LOG_ID)
      expect(log?.firstElementChild?.textContent).toBe('上次的对话（存在这台机器上）')
      expect(rows('user').map((r) => r.textContent)).toEqual(['帮我把这张图放大两倍'])
      expect(rows('assistant').map((r) => r.textContent)).toEqual(['先查一下可用的 skill', '已经好了'])
      expect(rows('assistant')[0]?.getAttribute('data-variant')).toBe('intermediate')
      expect(rows('assistant')[1]?.getAttribute('data-variant')).toBe('final')
      // 工具卡是同一套画法：结果按 id 配回调用那张，不另起一行
      expect(rows('tool')).toHaveLength(1)
      expect(rows('tool')[0]?.getAttribute('data-tool')).toBe('fake__do_it')
      expect(rows('tool')[0]?.getAttribute('data-state')).toBe('done')
    })

    it('says how many older messages the archive could not keep', async () => {
      installBridge({
        request: archive(archived({ dropped: 12, entries: [{ type: 'user', text: '很久以前问的' }] }))
      })
      setupDom()
      new Function(script)()
      await openPanel()

      expect(rows('agent').map((r) => r.textContent)).toEqual([
        '上次的对话（存在这台机器上）',
        '更早的 12 条超出存档上限，没留下来'
      ])
    })

    it('an archive that cannot be read is one line, not a silent blank', async () => {
      installBridge({
        request: archive({ ok: false, error: { code: -32603, message: '对话存档读不了（x.json）：坏了' } })
      })
      setupDom()
      new Function(script)()
      await openPanel()

      expect(rows('agent').map((r) => r.textContent)).toEqual([
        '取不回上次的对话: 对话存档读不了（x.json）：坏了'
      ])
      // 这是"上次的对话取不回来"，不是"这一轮失败了"：不该混进错误行。
      expect(rows('error')).toHaveLength(0)
    })

    it('an empty archive leaves the drawer blank', async () => {
      installBridge({ request: archive(archived({})) })
      setupDom()
      new Function(script)()
      await openPanel()

      expect(rows('agent')).toHaveLength(0)
      expect(document.getElementById(LOG_ID)?.childNodes).toHaveLength(0)
    })

    it('does not refill a drawer that is already showing this screen conversation', async () => {
      const bridge = installBridge({
        request: archive(archived({ entries: [{ type: 'user', text: '上次问的' }] }))
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await send('这一轮问的')

      document.getElementById(BTN_ID)?.click() // 关掉再开一遍
      await openPanel()

      const asked = bridge.request.mock.calls.filter((call) => call[0] === 'agent/history')
      expect(asked, 'history is only worth asking for an empty drawer').toHaveLength(1)
      expect(rows('user').map((r) => r.textContent)).toEqual(['上次问的', '这一轮问的'])
    })
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

  // ---- 审核节点：宿主问、人答、回答用 agent/answer 送回去 -------------------

  const askCards = (): Element[] =>
    Array.from(document.querySelectorAll(`#${LOG_ID} [data-kind="ask"]`))

  const optionLabels = (card: Element): string[] =>
    Array.from(card.querySelectorAll('.cs-ask-option')).map((o) => o.textContent ?? '')

  const noteOf = (card: Element): string => card.querySelector('.cs-ask-note')?.textContent ?? ''

  /** agent/answer 那次请求的参数，没发过就是 undefined。 */
  const answerCall = (
    request: ReturnType<typeof vi.fn>
  ): [string, Record<string, unknown>] | undefined =>
    request.mock.calls.find((call) => call[0] === 'agent/answer') as
      | [string, Record<string, unknown>]
      | undefined

  /**
   * 起一轮，并让 agent/chat 一直挂着——审核节点只在"一轮在飞"时才有落脚处。
   */
  const startTurn = async (request: ReturnType<typeof vi.fn>): Promise<void> => {
    installBridge({ request })
    setupDom()
    new Function(script)()
    await openPanel()
    const input = document.getElementById(INPUT_ID) as HTMLTextAreaElement
    input.value = '开始'
    document.getElementById(SEND_ID)?.click() // 不 await：这一轮在飞行中
    await flush()
  }

  const turnThen = (
    onAnswer: (params: Record<string, unknown>) => unknown
  ): ReturnType<typeof vi.fn> =>
    vi.fn((method: string, params: unknown) => {
      if (method === 'agent/chat') return new Promise(() => {}) // 这一轮不回来
      if (method === 'agent/answer') return onAnswer((params ?? {}) as Record<string, unknown>)
      return { ok: true, result: {} }
    })

  const askEvent = (overrides: Record<string, unknown> = {}): void => {
    emit({
      params: {
        type: 'ask_user',
        call_id: 'ask-1',
        question: '用哪套工作流？',
        options: ['SDXL', 'Flux'],
        ...overrides
      }
    })
  }

  it('paints the question and its options when the host asks', async () => {
    await startTurn(turnThen(() => ({ ok: true, result: { delivered: true } })))

    askEvent()

    const cards = askCards()
    expect(cards).toHaveLength(1)
    expect(cards[0]?.getAttribute('data-state')).toBe('waiting')
    expect(cards[0]?.querySelector('.cs-ask-q')?.textContent).toBe('用哪套工作流？')
    expect(optionLabels(cards[0]!)).toEqual(['SDXL', 'Flux'])
  })

  it('sends a clicked option back as the answer', async () => {
    const request = turnThen(() => ({ ok: true, result: { delivered: true } }))
    await startTurn(request)
    askEvent()

    const card = askCards()[0]!
    ;(card.querySelector('.cs-ask-option') as HTMLButtonElement).click()
    await flush()

    expect(answerCall(request)?.[1]).toEqual({ call_id: 'ask-1', answer: 'SDXL' })
    expect(card.getAttribute('data-state')).toBe('answered')
    expect(noteOf(card)).toContain('已回答：SDXL')
  })

  it('sends a typed answer, trimmed', async () => {
    const request = turnThen(() => ({ ok: true, result: { delivered: true } }))
    await startTurn(request)
    askEvent()

    const card = askCards()[0]!
    const input = card.querySelector('.cs-ask-input') as HTMLInputElement
    input.value = '  用 Flux 那套  '
    card.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
    await flush()

    expect(answerCall(request)?.[1]).toEqual({ call_id: 'ask-1', answer: '用 Flux 那套' })
  })

  it('allows a free answer when the host offered no options', async () => {
    const request = turnThen(() => ({ ok: true, result: { delivered: true } }))
    await startTurn(request)
    askEvent({ options: [] })

    const card = askCards()[0]!
    expect(optionLabels(card)).toEqual([])
    const input = card.querySelector('.cs-ask-input') as HTMLInputElement
    input.value = '随你'
    card.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
    await flush()

    expect(answerCall(request)?.[1]).toEqual({ call_id: 'ask-1', answer: '随你' })
  })

  it('says the answer was too late instead of pretending it landed', async () => {
    // 宿主已经不等了（超时/被停/已收过）：delivered:false。人答晚了不是错误。
    const request = turnThen(() => ({ ok: true, result: { call_id: 'ask-1', delivered: false } }))
    await startTurn(request)
    askEvent()

    const card = askCards()[0]!
    ;(card.querySelector('.cs-ask-option') as HTMLButtonElement).click()
    await flush()

    expect(card.getAttribute('data-state')).toBe('stale')
    expect(noteOf(card)).toContain('不等了')
  })

  it('reports a send failure on the card', async () => {
    const request = turnThen(() => ({ ok: false, error: { code: -32603, message: '宿主没在跑' } }))
    await startTurn(request)
    askEvent()

    const card = askCards()[0]!
    ;(card.querySelector('.cs-ask-option') as HTMLButtonElement).click()
    await flush()

    expect(card.getAttribute('data-state')).toBe('failed')
    expect(noteOf(card)).toContain('回答没送到: 宿主没在跑')
  })

  it('does not send anything twice for the same question', async () => {
    const request = turnThen(() => ({ ok: true, result: { delivered: true } }))
    await startTurn(request)
    askEvent()

    const card = askCards()[0]!
    const option = card.querySelector('.cs-ask-option') as HTMLButtonElement
    option.click()
    option.click() // 手抖点第二下：同一个回答不该送两遍
    await flush()

    const sent = request.mock.calls.filter((call) => call[0] === 'agent/answer')
    expect(sent).toHaveLength(1)
  })

  it('flags a card that carries no call_id instead of posting a stray answer', async () => {
    const request = turnThen(() => ({ ok: true, result: { delivered: true } }))
    await startTurn(request)
    askEvent({ call_id: undefined, options: [] })

    const card = askCards()[0]!
    const input = card.querySelector('.cs-ask-input') as HTMLInputElement
    input.value = '随便'
    card.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
    await flush()

    expect(answerCall(request)).toBeUndefined()
    expect(card.getAttribute('data-state')).toBe('failed')
    expect(noteOf(card)).toContain('call_id')
  })

  it('ignores an ask event that arrives with no turn in flight', () => {
    installBridge()
    setupDom()
    new Function(script)()

    askEvent()

    expect(askCards()).toHaveLength(0)
  })

  // ---- 灵感输入：一句话拆成多步清单，用户点头或要改 -------------------------

  const planCards = (): Element[] =>
    Array.from(document.querySelectorAll(`#${LOG_ID} [data-kind="plan"]`))

  const planNote = (card: Element): string => card.querySelector('.cs-plan-note')?.textContent ?? ''

  /** 每步第一行才是"这一步做什么"，后头挂的工具名/备注不算标题。 */
  const stepTitles = (card: Element): string[] =>
    Array.from(card.querySelectorAll('.cs-plan-step')).map(
      (step) => step.firstElementChild?.textContent ?? ''
    )

  const stepStates = (card: Element): (string | null)[] =>
    Array.from(card.querySelectorAll('.cs-plan-step')).map((step) =>
      step.getAttribute('data-step-state')
    )

  /** agent/plan_result 那次请求的参数，没发过就是 undefined。 */
  const planCall = (
    request: ReturnType<typeof vi.fn>
  ): [string, Record<string, unknown>] | undefined =>
    request.mock.calls.find((call) => call[0] === 'agent/plan_result') as
      | [string, Record<string, unknown>]
      | undefined

  /** 与 turnThen 同形，只是回程换成了 agent/plan_result。 */
  const planTurnThen = (
    onVerdict: (params: Record<string, unknown>) => unknown
  ): ReturnType<typeof vi.fn> =>
    vi.fn((method: string, params: unknown) => {
      if (method === 'agent/chat') return new Promise(() => {}) // 这一轮停在等人过目
      if (method === 'agent/plan_result')
        return onVerdict((params ?? {}) as Record<string, unknown>)
      return { ok: true, result: {} }
    })

  const planEvent = (overrides: Record<string, unknown> = {}): void => {
    emit({
      params: {
        type: 'plan',
        call_id: 'plan-1',
        goal: '把这张图改成赛博朋克海报感',
        steps: [
          { title: '先用 SDXL 出一版草稿', tool: 'comfy_run_skill' },
          { title: '再把草稿放大到 2K' }
        ],
        notes: '第 2 步放大比较吃显存',
        ...overrides
      }
    })
  }

  const progressEvent = (overrides: Record<string, unknown> = {}): void => {
    emit({ params: { type: 'plan_progress', step: 1, status: 'running', ...overrides } })
  }

  it('paints the plan and its steps when the host submits one', async () => {
    await startTurn(planTurnThen(() => ({ ok: true, result: { delivered: true } })))

    planEvent()

    const cards = planCards()
    expect(cards).toHaveLength(1)
    expect(cards[0]?.getAttribute('data-state')).toBe('waiting')
    expect(cards[0]?.querySelector('.cs-plan-goal')?.textContent).toBe('把这张图改成赛博朋克海报感')
    expect(stepTitles(cards[0]!)).toEqual(['先用 SDXL 出一版草稿', '再把草稿放大到 2K'])
    expect(cards[0]?.querySelector('.cs-plan-tool')?.textContent).toBe('comfy_run_skill')
    expect(cards[0]?.querySelector('.cs-plan-notes')?.textContent).toBe('第 2 步放大比较吃显存')
    expect(stepStates(cards[0]!)).toEqual(['pending', 'pending'])
  })

  it('sends approval back when the user takes the plan as it is', async () => {
    const request = planTurnThen(() => ({ ok: true, result: { delivered: true } }))
    await startTurn(request)
    planEvent()

    const card = planCards()[0]!
    ;(card.querySelector('.cs-plan-ok') as HTMLButtonElement).click()
    await flush()

    expect(planCall(request)?.[1]).toEqual({ call_id: 'plan-1', approved: true, feedback: '' })
    expect(card.getAttribute('data-state')).toBe('approved')
  })

  it('sends the change request back when the user rejects the plan', async () => {
    const request = planTurnThen(() => ({ ok: true, result: { delivered: true } }))
    await startTurn(request)
    planEvent()

    const card = planCards()[0]!
    ;(card.querySelector('.cs-plan-change') as HTMLButtonElement).click()
    expect(card.getAttribute('data-state')).toBe('editing')

    const input = card.querySelector('.cs-plan-input') as HTMLTextAreaElement
    input.value = '  第 2 步换成 Flux 那套  '
    card.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
    await flush()

    expect(planCall(request)?.[1]).toEqual({
      call_id: 'plan-1',
      approved: false,
      feedback: '第 2 步换成 Flux 那套'
    })
    expect(card.getAttribute('data-state')).toBe('rejected')
    expect(planNote(card)).toContain('第 2 步换成 Flux 那套')
  })

  it('refuses to send a rejection without saying what to change', async () => {
    const request = planTurnThen(() => ({ ok: true, result: { delivered: true } }))
    await startTurn(request)
    planEvent()

    const card = planCards()[0]!
    ;(card.querySelector('.cs-plan-change') as HTMLButtonElement).click()
    card.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
    await flush()

    // 宿主那边也会挡（feedback 非空），就地提醒省得白跑一趟。
    expect(planCall(request)).toBeUndefined()
    expect(card.getAttribute('data-state')).toBe('editing')
    expect(planNote(card)).toContain('要改哪里')
  })

  it('marks the step the host reports progress on', async () => {
    await startTurn(planTurnThen(() => ({ ok: true, result: { delivered: true } })))
    planEvent()
    progressEvent({ step: 2, status: 'done', note: '放大完了' })

    const card = planCards()[0]!
    expect(stepStates(card)).toEqual(['pending', 'done'])
    expect(card.querySelector('.cs-plan-step[data-step="2"] .cs-plan-progress')?.textContent).toBe(
      '放大完了'
    )
  })

  it('starts a fresh line when the progress does not match the list', async () => {
    await startTurn(planTurnThen(() => ({ ok: true, result: { delivered: true } })))
    planEvent()
    progressEvent({ step: 5, status: 'failed' })

    // 对不上也照样让人看见，而不是静默丢掉。
    const lines = Array.from(document.querySelectorAll(`#${LOG_ID} [data-kind="agent"]`))
    expect(lines[lines.length - 1]?.textContent).toContain('第 5 步 失败')
    expect(stepStates(planCards()[0]!)).toEqual(['pending', 'pending'])
  })

  it('reports a late verdict as stale rather than an error', async () => {
    const request = planTurnThen(() => ({
      ok: true,
      result: { call_id: 'plan-1', delivered: false }
    }))
    await startTurn(request)
    planEvent()

    const card = planCards()[0]!
    ;(card.querySelector('.cs-plan-ok') as HTMLButtonElement).click()
    await flush()

    expect(card.getAttribute('data-state')).toBe('stale')
    expect(planNote(card)).toContain('不等了')
  })

  it('reports a verdict the host refused', async () => {
    const request = planTurnThen(() => ({
      ok: false,
      error: { code: -32602, message: 'feedback 不能为空' }
    }))
    await startTurn(request)
    planEvent()

    const card = planCards()[0]!
    ;(card.querySelector('.cs-plan-change') as HTMLButtonElement).click()
    const input = card.querySelector('.cs-plan-input') as HTMLTextAreaElement
    input.value = '换个模型'
    card.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
    await flush()

    expect(card.getAttribute('data-state')).toBe('failed')
    expect(planNote(card)).toContain('没送到: feedback 不能为空')
  })

  it('flags a plan card that carries no call_id instead of posting a stray verdict', async () => {
    const request = planTurnThen(() => ({ ok: true, result: { delivered: true } }))
    await startTurn(request)
    planEvent({ call_id: undefined })

    const card = planCards()[0]!
    ;(card.querySelector('.cs-plan-ok') as HTMLButtonElement).click()
    await flush()

    expect(planCall(request)).toBeUndefined()
    expect(card.getAttribute('data-state')).toBe('failed')
    expect(planNote(card)).toContain('call_id')
  })

  it('ignores a plan event that arrives with no turn in flight', () => {
    installBridge()
    setupDom()
    new Function(script)()

    planEvent()

    expect(planCards()).toHaveLength(0)
  })
})
