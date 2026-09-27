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
const AGENT_ID = 'comfy-desktop-studio-chat-agent'
const SESSION_ID = 'comfy-desktop-studio-chat-session'
const SESSION_NEW_ID = 'comfy-desktop-studio-chat-session-new'
const SESSION_CLOSE_ID = 'comfy-desktop-studio-chat-session-close'
const STORAGE_ID = 'comfy-desktop-studio-chat-storage'
const TABS_ID = 'comfy-desktop-studio-chat-tabs'
const CHAT_VIEW_ID = 'comfy-desktop-studio-chat-view'
const NOVEL_VIEW_ID = 'comfy-desktop-studio-novel-view'
const NOVEL_LIST_ID = 'comfy-desktop-studio-novel-list'
const NOVEL_HINT_ID = 'comfy-desktop-studio-novel-hint'
const NOVEL_FORM_ID = 'comfy-desktop-studio-novel-form'
const NOVEL_PATH_ID = 'comfy-desktop-studio-novel-path'
const NOVEL_READER_ID = 'comfy-desktop-studio-novel-reader'
const NOVEL_PAGER_ID = 'comfy-desktop-studio-novel-pager'

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

  /** `agent/agents` 的回包；`extra` 用来塞 missing / problems / error 这些边角。 */
  const agentsCatalog = (
    list: Array<{ id: string; name: string; summary?: string }>,
    current: string,
    extra: Record<string, unknown> = {}
  ): unknown => ({
    ok: true,
    result: {
      current,
      missing: null,
      agents: list,
      problems: [],
      error: null,
      dir: 'D:\\data\\agents',
      ...extra
    }
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
    // 面板只往浏览器存储里记一件事："上次停在哪一段"。别让上一个用例的那一段漏进下一个。
    window.localStorage.clear()
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

    // 一段对话 = 一个 session_id：这一轮要说到**当前这一段**上（面板默认是 default）。
    expect(bridge.request).toHaveBeenCalledWith('agent/chat', {
      text: '帮我把这张图放大两倍',
      session_id: 'default'
    })
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

  describe('many conversations side by side', () => {
    /**
     * 只有会话那两件事走自己的桩：开抽屉时面板还会问模型目录与 host/info，那些保持默认。
     * `row` 就是宿主 agent/sessions 给的一行（见 lib/comfy_studio/server.py）。
     */
    const row = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
      session_id: 'default',
      live: true,
      busy: false,
      messages: 2,
      saved_at: '2026-09-27T10:00:00+00:00',
      title: '帮我把这张图放大两倍',
      file: 'aaaa.json',
      error: null,
      ...over
    })

    const host = (
      sessions: unknown,
      over: { history?: unknown } = {}
    ): RequestStub => (method: string) => {
      if (method === 'agent/sessions') return { ok: true, result: { sessions, live: 1, max_sessions: 8 } }
      if (method === 'agent/history') return over.history ?? { ok: true, result: { entries: [] } }
      return { ok: true, result: { text: '答案在此' } }
    }

    const picker = (): HTMLSelectElement =>
      document.getElementById(SESSION_ID) as HTMLSelectElement
    const state = (): { session?: string } =>
      Reflect.get(window, '__comfyStudioChat') as { session?: string }

    it('opens on the conversation it was last on, and says when it cannot remember', async () => {
      window.localStorage.setItem('comfyStudio.session', 'chat-xyz')
      const bridge = installBridge({ request: host([]) })
      setupDom()
      new Function(script)()
      await openPanel()

      // 面板只记得"停在哪一段"；那一段的话由宿主喂回来（面板这屏重载过也一样接着聊）。
      expect(bridge.request).toHaveBeenCalledWith('agent/history', { session_id: 'chat-xyz' })
      expect(picker().value).toBe('chat-xyz')
      expect(picker().options).toHaveLength(1)
      expect(picker().options[0]?.textContent).toContain('（当前）')
    })

    it('says so when the browser storage cannot be read', async () => {
      // 隐私模式 / 被禁用：读不出来就说"这次记不住"，别拿默认那段冒充上次那段。
      const spy = vi.spyOn(window.localStorage, 'getItem').mockImplementation(() => {
        throw new Error('denied')
      })
      try {
        installBridge({ request: host([row()]) })
        setupDom()
        new Function(script)()
        await openPanel()

        expect(state().session, '读不到记忆中那一段就退回默认那段').toBe('default')
        expect(picker().title).toContain('浏览器存储用不了')
      } finally {
        spy.mockRestore()
      }
    })

    it('lists the conversations the host knows, current one included', async () => {
      installBridge({
        request: host([
          row(),
          row({ session_id: 'chat-2', live: false, title: '赛博朋克海报', messages: 6 }),
          row({ session_id: 'chat-3', live: true, busy: true, title: '', messages: 0 })
        ])
      })
      setupDom()
      new Function(script)()
      await openPanel()

      expect(Array.from(picker().options).map((o) => o.value)).toEqual([
        'default',
        'chat-2',
        'chat-3'
      ])
      const labels = Array.from(picker().options).map((o) => o.textContent ?? '')
      expect(labels[0]).toBe('帮我把这张图放大两倍 · 2 条（当前）')
      expect(labels[1], '只在存档里的一段也说清它不占位子').toBe('赛博朋克海报 · 6 条（存档里）')
      expect(labels[2], '在跑的那段标出来，也说明它还没说过话').toBe('（还没说话） · 0 条（在跑）')
    })

    it('switching repaints the drawer from that conversation archive', async () => {
      const bridge = installBridge({
        request: (method: string, params: unknown): unknown => {
          if (method === 'agent/sessions') {
            return {
              ok: true,
              result: {
                sessions: [row(), row({ session_id: 'chat-2', title: '赛博朋克海报' })],
                max_sessions: 8
              }
            }
          }
          if (method === 'agent/history') {
            const asked = (params as { session_id?: string } | null)?.session_id
            return asked === 'chat-2'
              ? { ok: true, result: { entries: [{ type: 'user', text: '赛博朋克海报' }] } }
              : { ok: true, result: { entries: [{ type: 'user', text: '这张图放大两倍' }] } }
          }
          return { ok: true, result: { text: '答案在此' } }
        }
      })
      setupDom()
      new Function(script)()
      await openPanel()
      expect(rows('user').map((r) => r.textContent)).toEqual(['这张图放大两倍'])

      picker().value = 'chat-2'
      picker().dispatchEvent(new Event('change'))
      await flush()

      expect(state().session).toBe('chat-2')
      const asked = bridge.request.mock.calls.filter((call) => call[0] === 'agent/history')
      expect(asked[asked.length - 1]).toEqual(['agent/history', { session_id: 'chat-2' }])
      expect(rows('user').map((r) => r.textContent)).toEqual(['赛博朋克海报'])
      // 换过来画的是**这一段**，不是"上次的"：标签得跟着变，别让人以为串了。
      expect(rows('agent')[0]?.textContent).toBe('这一段对话（存在这台机器上）')
    })

    it('does not paint a conversation the user already left', async () => {
      // 换段是异步的：手快的人点完 chat-3 又点 chat-2 时，chat-3 的"取历史"可能后回来。
      // 照单全收就成了两段话混在一屏上，而下拉说的是 chat-2 —— 所以票对不上就一句都不画。
      const parked: Array<(value: unknown) => void> = []
      installBridge({
        request: (method: string, params: unknown): unknown => {
          if (method === 'agent/sessions') {
            return {
              ok: true,
              result: {
                sessions: [row(), row({ session_id: 'chat-2' }), row({ session_id: 'chat-3' })],
                max_sessions: 8
              }
            }
          }
          if (method === 'agent/history') {
            const asked = (params as { session_id?: string } | null)?.session_id
            if (asked === 'chat-3') {
              // 这一段慢：先挂着，等用户换走之后再放它回来（模拟"响应迟到"）。
              return new Promise((resolve) => {
                parked.push(resolve)
              })
            }
            return {
              ok: true,
              result: { entries: [{ type: 'user', text: '这是 ' + asked + ' 的话' }] }
            }
          }
          return { ok: true, result: { text: '答案在此' } }
        }
      })
      setupDom()
      new Function(script)()
      await openPanel()
      expect(rows('user').map((r) => r.textContent)).toEqual(['这是 default 的话'])

      picker().value = 'chat-3'
      picker().dispatchEvent(new Event('change'))
      await flush()
      picker().value = 'chat-2'
      picker().dispatchEvent(new Event('change'))
      await flush()
      expect(state().session).toBe('chat-2')
      expect(rows('user').map((r) => r.textContent)).toEqual(['这是 chat-2 的话'])

      // 迟到的 chat-3 现在回来了：不许画。
      parked.forEach((resolve) =>
        resolve({ ok: true, result: { entries: [{ type: 'user', text: '这是 chat-3 的话' }] } })
      )
      await flush()
      expect(rows('user').map((r) => r.textContent)).toEqual(['这是 chat-2 的话'])
      expect(rows('agent').map((r) => r.textContent)).toEqual(['这一段对话（存在这台机器上）'])
    })

    it('says a switched-to conversation has nothing in it yet', async () => {
      installBridge({
        request: host([row(), row({ session_id: 'chat-2', title: '空的那段', messages: 0 })])
      })
      setupDom()
      new Function(script)()
      await openPanel()

      picker().value = 'chat-2'
      picker().dispatchEvent(new Event('change'))
      await flush()

      expect(rows('agent').map((r) => r.textContent)).toEqual([
        '这一段对话（存在这台机器上）',
        '这一段还没说过话'
      ])
    })

    it('keeps a broken archive visible but not pickable', async () => {
      installBridge({
        request: host([
          row(),
          { session_id: '', file: 'deadbeef.json', error: '对话存档读不了（…deadbeef.json）：坏了' }
        ])
      })
      setupDom()
      new Function(script)()
      await openPanel()

      const broken = picker().options[1]
      expect(broken?.textContent).toBe('读不了：deadbeef.json')
      expect(broken?.disabled).toBe(true)
      expect(broken?.title).toContain('deadbeef.json')
    })

    it('keeps the list it already showed when a refresh fails', async () => {
      // 宿主抖一下、或它刚重启时刷新会失败：这时候把下拉清空，用户看到的就是"别的对话
      // 都没了"——比"这一次没读到"吓人得多。留着上一份，把失败如实说出来。
      let failing = false
      installBridge({
        request: (method: string): unknown => {
          if (method === 'agent/sessions') {
            if (failing) return { ok: false, error: { code: -32603, message: '宿主忙' } }
            return {
              ok: true,
              result: {
                sessions: [row(), row({ session_id: 'chat-2', title: '赛博朋克海报' })],
                max_sessions: 8
              }
            }
          }
          return { ok: true, result: { entries: [] } }
        }
      })
      setupDom()
      new Function(script)()
      await openPanel()
      expect(Array.from(picker().options).map((o) => o.value)).toEqual(['default', 'chat-2'])

      failing = true
      document.getElementById(SESSION_NEW_ID)?.click() // 新开会顺带刷新一次清单
      await flush()

      expect(
        Array.from(picker().options).map((o) => o.value),
        '别的对话还在下拉里'
      ).toContain('chat-2')
      expect(picker().title).toContain('读会话清单失败')
    })

    it('starts a new conversation with an id of its own and says so', async () => {
      const bridge = installBridge({ request: host([row()]) })
      setupDom()
      new Function(script)()
      await openPanel()

      document.getElementById(SESSION_NEW_ID)?.click()
      await flush()

      const fresh = state().session
      expect(fresh, '新的一段要换个 id，不能还写在 default 上').not.toBe('default')
      expect(fresh).toMatch(/^chat-/)
      expect(document.getElementById(LOG_ID)?.childNodes).toHaveLength(0)
      expect(picker().value).toBe(fresh)
      expect(document.getElementById(STATUS_ID)?.textContent).toContain('新的一段对话')

      // 下一句要落到新那一段上。
      await send('新的一段第一句')
      expect(bridge.request).toHaveBeenCalledWith('agent/chat', {
        text: '新的一段第一句',
        session_id: fresh
      })
    })

    it('closing hands the conversation back and moves on to a new one', async () => {
      const bridge = installBridge({
        request: (method: string): unknown => {
          if (method === 'host/info') {
            return { ok: true, result: { history: true, memory: true, memory_entries: 0 } }
          }
          if (method === 'agent/sessions') {
            return { ok: true, result: { sessions: [row()], max_sessions: 8 } }
          }
          if (method === 'agent/close') {
            return { ok: true, result: { session_id: 'default', closed: true, history_kept: true } }
          }
          return { ok: true, result: { text: '答案在此' } }
        }
      })
      setupDom()
      new Function(script)()
      await openPanel()

      document.getElementById(SESSION_CLOSE_ID)?.click()
      await flush()

      expect(bridge.request).toHaveBeenCalledWith('agent/close', { session_id: 'default' })
      // 关掉 = 腾位子，对话留在存档里：这话得说出来，用户才敢关。
      expect(document.getElementById(STATUS_ID)?.textContent).toBe(
        '已关掉这一段；对话留在存档里，选它就能接着说'
      )
      expect(state().session).not.toBe('default')
      expect(rows('error')).toHaveLength(0)
    })

    it('can go back to a conversation it just closed', async () => {
      // 关掉 = 腾位子，不是清对话：从下拉把它选回来，面板该让宿主把存档喂回来接着聊。
      installBridge({
        request: (method: string, params: unknown): unknown => {
          if (method === 'host/info') {
            return { ok: true, result: { history: true, memory: true, memory_entries: 0 } }
          }
          if (method === 'agent/sessions') {
            return { ok: true, result: { sessions: [row()], max_sessions: 8 } }
          }
          if (method === 'agent/close') {
            return { ok: true, result: { session_id: 'default', closed: true, history_kept: true } }
          }
          if (method === 'agent/history') {
            const asked = (params as { session_id?: string } | null)?.session_id
            return {
              ok: true,
              result:
                asked === 'default'
                  ? { entries: [{ type: 'user', text: '关掉前说的话' }] }
                  : { entries: [] }
            }
          }
          return { ok: true, result: { text: '答案在此' } }
        }
      })
      setupDom()
      new Function(script)()
      await openPanel()

      document.getElementById(SESSION_CLOSE_ID)?.click()
      await flush()
      expect(state().session).not.toBe('default')

      picker().value = 'default'
      picker().dispatchEvent(new Event('change'))
      await flush()

      expect(state().session).toBe('default')
      expect(rows('user').map((r) => r.textContent)).toEqual(['关掉前说的话'])
    })

    it('asks again before dropping a conversation when there is no archive', async () => {
      const bridge = installBridge({
        request: (method: string): unknown => {
          if (method === 'host/info') {
            return { ok: true, result: { history: false, memory: true, memory_entries: 0 } }
          }
          if (method === 'agent/sessions') return { ok: true, result: { sessions: [row()] } }
          return { ok: true, result: { text: '答案在此' } }
        }
      })
      setupDom()
      new Function(script)()
      await openPanel()

      document.getElementById(SESSION_CLOSE_ID)?.click()
      await flush()

      const closed = bridge.request.mock.calls.filter((call) => call[0] === 'agent/close')
      expect(closed, '这一档下关掉就是丢掉，得先问一句').toHaveLength(0)
      expect(document.getElementById(STATUS_ID)?.textContent).toContain('--no-history')
      expect(state().session, '还没关，这一段还在').toBe('default')

      document.getElementById(SESSION_CLOSE_ID)?.click()
      await flush()

      expect(bridge.request).toHaveBeenCalledWith('agent/close', { session_id: 'default' })
    })

    it('asks again when the host never said whether there is an archive', async () => {
      // 拿不到 host/info 就是"存不存不知道"：那时也先当成可能会丢，多问一句——
      // 宁可多点一下，也别在一次点击里丢掉一段可能没有存档的对话。
      const bridge = installBridge({
        request: (method: string): unknown =>
          method === 'agent/sessions' ? { ok: true, result: { sessions: [row()] } } : { ok: true, result: { text: '答案在此' } }
      })
      setupDom()
      new Function(script)()
      await openPanel()

      document.getElementById(SESSION_CLOSE_ID)?.click()
      await flush()

      expect(bridge.request.mock.calls.filter((call) => call[0] === 'agent/close')).toHaveLength(0)
      expect(document.getElementById(STATUS_ID)?.textContent).toContain('还没问到')
    })

    it('locks the session row while a turn is in flight', async () => {
      installBridge({
        request: (method: string): unknown =>
          method === 'agent/chat' ? new Promise(() => {}) : host([row()])(method, null)
      })
      setupDom()
      new Function(script)()
      await openPanel()

      const select = picker()
      const add = document.getElementById(SESSION_NEW_ID) as HTMLButtonElement
      const close = document.getElementById(SESSION_CLOSE_ID) as HTMLButtonElement
      expect(select.disabled).toBe(false)

      const input = document.getElementById(INPUT_ID) as HTMLTextAreaElement
      input.value = '跑个 skill'
      document.getElementById(SEND_ID)?.click() // 不 await：让这一轮停在飞行中

      // 换走会把这一轮的回答画到别的对话上；关掉会把活劈了（宿主那边也会拒）。
      expect(select.disabled).toBe(true)
      expect(add.disabled).toBe(true)
      expect(close.disabled).toBe(true)
    })
  })

  describe('where it keeps things on this machine', () => {
    /** 开抽屉时面板会问几件事（模型目录、上次的对话、host/info）；只有 host/info 走自己的桩。 */
    const hostInfo = (result: Record<string, unknown> | null): RequestStub => (method) =>
      method === 'host/info'
        ? result === null
          ? { ok: false, error: { message: '宿主没起来' } }
          : { ok: true, result }
        : { ok: true, result: { text: '答案在此' } }

    const line = (): HTMLElement | null => document.getElementById(STORAGE_ID)

    const paths = {
      memory_file: 'C:\\Users\\me\\AppData\\Roaming\\comfy-studio\\memory.json',
      history_dir: 'C:\\Users\\me\\AppData\\Roaming\\comfy-studio\\sessions'
    }

    it('says how much it remembers and that it all stays on this machine', async () => {
      installBridge({
        request: hostInfo({ ...paths, memory: true, memory_entries: 3, history: true })
      })
      setupDom()
      new Function(script)()
      await openPanel()

      expect(line()?.textContent).toBe('它记着 3 条事；对话存在这台机器上')
      // 路径太长，铺在界面上要占掉半个抽屉：放悬停提示里
      expect(line()?.title).toContain('memory.json')
      expect(line()?.title).toContain('sessions')
    })

    it('puts an unreadable memory file in front, since every turn fails on it', async () => {
      const broken = '记忆文件读不了（' + paths.memory_file + '）：Expecting value: line 1 column 1'
      installBridge({
        request: hostInfo({
          ...paths,
          memory: true,
          memory_entries: null,
          history: true,
          memory_error: broken
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()

      expect(line()?.textContent).toContain('记忆读不了')
      expect(line()?.textContent, '写出是哪个文件，用户才能去修它').toContain('memory.json')
      expect(line()?.getAttribute('data-tone'), '这不是小事，要报红').toBe('error')
      expect(line()?.title, '原文里连怎么办都写着').toBe(broken)
    })

    it('says out loud when the host was started without memory or the archive', async () => {
      installBridge({ request: hostInfo({ memory: false, history: false }) })
      setupDom()
      new Function(script)()
      await openPanel()

      expect(line()?.textContent).toBe(
        '这次没开记忆（--no-memory），你说过的事它不会记住；' +
          '这次没开对话存档（--no-history），面板一关这段对话就没了'
      )
    })

    it('does not guess at fields the host did not report', async () => {
      installBridge({ request: hostInfo({}) })
      setupDom()
      new Function(script)()
      await openPanel()

      expect(line()?.textContent).toBe('记忆开没开它没说；对话存不存它没说')
    })

    it('says so when the host cannot be asked at all', async () => {
      installBridge({ request: hostInfo(null) })
      setupDom()
      new Function(script)()
      await openPanel()

      expect(line()?.textContent).toBe('看不清它把记忆和对话存在哪: 宿主没起来')
      expect(line()?.getAttribute('data-tone')).toBe('error')
    })

    it('re-reads the memory count once a turn settles', async () => {
      let entries = 0
      installBridge({
        request: (method: string) =>
          method === 'host/info'
            ? { ok: true, result: { memory: true, memory_entries: entries, history: true } }
            : { ok: true, result: { text: '答案在此' } }
      })
      setupDom()
      new Function(script)()
      await openPanel()
      expect(line()?.textContent).toBe('还没记住什么；对话存在这台机器上')

      entries = 1 // 这一轮里它记下了一条
      await send('记住我喜欢方形构图')
      await flush() // 这一问是收尾时才发的，多让一拍

      expect(line()?.textContent).toBe('它记着 1 条事；对话存在这台机器上')
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

  it('fills the agent picker from the host catalog when the drawer opens', async () => {
    const request = vi.fn((method: string) =>
      method === 'agent/agents'
        ? agentsCatalog(
            [
              { id: 'general', name: '通用助手', summary: '什么都能问' },
              { id: 'artist', name: '画师', summary: '只谈出图' }
            ],
            'artist'
          )
        : { ok: true, result: { text: '答案在此' } }
    )
    installBridge({ request })
    setupDom()
    new Function(script)()

    expect(document.getElementById(AGENT_ID), 'picker is part of the drawer').toBeNull()

    await openPanel()

    // 开抽屉会连着问几样（模型、智能体、历史、会话…），只看问了没有，不认它排第几。
    expect(request.mock.calls.map((call) => call[0])).toContain('agent/agents')
    const picker = document.getElementById(AGENT_ID) as HTMLSelectElement
    expect(Array.from(picker.options).map((o) => o.value)).toEqual(['general', 'artist'])
    expect(Array.from(picker.options).map((o) => o.textContent)).toEqual(['通用助手', '画师'])
    expect(picker.options[0]?.title, 'files carry their own summary').toBe('什么都能问')
    expect(picker.value, 'current agent is preselected').toBe('artist')
    expect(picker.disabled).toBe(false)
    expect(picker.title, 'tooltip says where user agents live').toContain('D:\\data\\agents')
  })

  it('switches the agent through the host and names the new persona', async () => {
    const request = vi.fn((method: string) => {
      if (method === 'agent/agents')
        return agentsCatalog([{ id: 'general', name: '通用' }, { id: 'artist', name: '画师' }], 'general')
      if (method === 'agent/agent')
        return { ok: true, result: { agent: 'artist', changed: true, name: '画师', error: null } }
      return { ok: true, result: { text: '答案在此' } }
    })
    installBridge({ request })
    setupDom()
    new Function(script)()
    await openPanel()

    const picker = document.getElementById(AGENT_ID) as HTMLSelectElement
    picker.value = 'artist'
    picker.dispatchEvent(new Event('change'))
    await flush()

    expect(request).toHaveBeenCalledWith('agent/agent', { agent: 'artist' })
    expect(document.getElementById(STATUS_ID)?.textContent).toContain('画师')
    expect(document.getElementById(STATUS_ID)?.textContent).toContain('下一次提问')
    expect(picker.value).toBe('artist')
    expect(picker.disabled).toBe(false)
    expect(rows('error'), 'a successful switch must not paint an error').toHaveLength(0)
  })

  it('rolls the agent picker back when the host rejects the switch', async () => {
    const request = vi.fn((method: string) => {
      if (method === 'agent/agents')
        return agentsCatalog([{ id: 'general', name: '通用' }, { id: 'ghost', name: '幽灵' }], 'general')
      if (method === 'agent/agent')
        return { ok: false, error: { code: -32602, message: '没有这个智能体' } }
      return { ok: true, result: { text: '答案在此' } }
    })
    installBridge({ request })
    setupDom()
    new Function(script)()
    await openPanel()

    const picker = document.getElementById(AGENT_ID) as HTMLSelectElement
    picker.value = 'ghost'
    picker.dispatchEvent(new Event('change'))
    await flush()

    expect(picker.value, 'selection falls back to the agent actually in use').toBe('general')
    expect(rows('error').map((r) => r.textContent)).toEqual([
      '换智能体失败: 没有这个智能体（错误码 -32602）'
    ])
    expect(picker.disabled).toBe(false)
  })

  it('draws unreadable agent files as disabled rows instead of dropping them', async () => {
    const request = vi.fn((method: string) =>
      method === 'agent/agents'
        ? agentsCatalog([{ id: 'general', name: '通用' }], 'general', {
            problems: [{ file: 'broken.md', error: '文件读不了: boom' }]
          })
        : { ok: true, result: { text: '答案在此' } }
    )
    installBridge({ request })
    setupDom()
    new Function(script)()
    await openPanel()

    const picker = document.getElementById(AGENT_ID) as HTMLSelectElement
    const bad = picker.options[picker.options.length - 1]
    expect(bad?.textContent).toBe('broken.md（读不了）')
    expect(bad?.title).toBe('文件读不了: boom')
    expect(bad?.disabled, 'a broken row must not be selectable').toBe(true)
    expect(picker.title, 'the tooltip names the unreadable files').toContain('broken.md')
  })

  it('keeps a selected agent that vanished visibly unselected', async () => {
    const request = vi.fn((method: string) =>
      method === 'agent/agents'
        ? agentsCatalog([{ id: 'general', name: '通用' }], 'ghost', {
            missing: '选中的智能体 不在了（文件被删掉或改名了？）'
          })
        : { ok: true, result: { text: '答案在此' } }
    )
    installBridge({ request })
    setupDom()
    new Function(script)()
    await openPanel()

    const picker = document.getElementById(AGENT_ID) as HTMLSelectElement
    expect(picker.value, 'pretending the gone agent is still selected would lie').toBe('')
    expect(picker.selectedIndex).toBe(-1)
    expect(picker.title).toContain('不在了')
    expect(picker.disabled, 'the remaining agent is still selectable').toBe(false)
  })

  it('locks the agent picker while a turn is in flight', async () => {
    const request = vi.fn((method: string) =>
      method === 'agent/agents'
        ? agentsCatalog([{ id: 'general', name: '通用' }], 'general')
        : { ok: true, result: { text: '答案在此' } }
    )
    installBridge({ request })
    setupDom()
    new Function(script)()
    await openPanel()

    const picker = document.getElementById(AGENT_ID) as HTMLSelectElement
    expect(picker.disabled).toBe(false)

    const input = document.getElementById(INPUT_ID) as HTMLTextAreaElement
    input.value = '跑个 skill'
    document.getElementById(SEND_ID)?.click() // 不 await：这一轮在飞行中
    expect(picker.disabled, 'swapping the persona mid-turn would be confusing').toBe(true)

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

  describe('管理小说', () => {
    /** 原文目录是宿主给的（见 lib/comfy_studio/novels.py）：面板一个路径都不拼，只照着用。 */
    const novelDir = 'D:/comfy/custom_nodes/comfy_studio/manju/novel'

    /** 宿主 novels/list 里的一行。 */
    const novelRow = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
      name: '长夜.txt',
      bytes: 2048,
      mtime: 1758900000,
      text: true,
      ...over
    })

    const listing = (novels: unknown[], over: Record<string, unknown> = {}): unknown => ({
      ok: true,
      result: {
        dir: novelDir,
        exists: true,
        matched: novels.length,
        returned: novels.length,
        truncated: false,
        limit: 200,
        novels,
        ...over
      }
    })

    /** 只有 novels/* 那几件事走自己的桩；开抽屉时要问的那些保持默认。 */
    const host = (handlers: Record<string, unknown>): RequestStub => (method, params) =>
      method in handlers
        ? typeof handlers[method] === 'function'
          ? (handlers[method] as RequestStub)(method, params)
          : handlers[method]
        : { ok: true, result: { text: '答案在此' } }

    const view = (id: string): HTMLElement => document.getElementById(id) as HTMLElement
    const hintLine = (): HTMLElement => view(NOVEL_HINT_ID)
    const tab = (label: string): HTMLButtonElement | undefined =>
      Array.from(document.querySelectorAll<HTMLButtonElement>(`#${TABS_ID} .cs-tab`)).find(
        (b) => b.textContent === label
      )
    const button = (scopeId: string, text: string): HTMLButtonElement | null =>
      Array.from(document.querySelectorAll<HTMLButtonElement>(`#${scopeId} button`)).find(
        (b) => b.textContent === text
      ) ?? null
    const lineButton = (name: string, text: string): HTMLButtonElement | null => {
      const line = document.querySelector(`#${NOVEL_LIST_ID} .cs-novel-row[data-name="${name}"]`)
      const buttons = Array.from(line?.querySelectorAll('button') ?? [])
      return buttons.find((b) => b.textContent === text) ?? null
    }
    const novelLine = (name: string): Element | null =>
      document.querySelector(`#${NOVEL_LIST_ID} .cs-novel-row[data-name="${name}"]`)
    const pathInput = (): HTMLInputElement =>
      document.getElementById(NOVEL_PATH_ID) as HTMLInputElement
    const novelCalls = (bridge: StudioBridge, method: string): unknown[][] =>
      bridge.request.mock.calls.filter((call: unknown[]) => call[0] === method)

    const openNovels = async (): Promise<void> => {
      tab('管理小说')?.click()
      await flush()
    }

    it('only asks the host for novels once that page is opened', async () => {
      const bridge = installBridge({ request: host({ 'novels/list': listing([]) }) })
      setupDom()
      new Function(script)()
      await openPanel()

      expect(view(CHAT_VIEW_ID).style.display).toBe('flex')
      expect(view(NOVEL_VIEW_ID).style.display).toBe('none')
      expect(novelCalls(bridge, 'novels/list'), '没打开这一页就别去动人家的书库').toHaveLength(0)

      await openNovels()

      expect(view(CHAT_VIEW_ID).style.display).toBe('none')
      expect(view(NOVEL_VIEW_ID).style.display).toBe('flex')
      expect(tab('管理小说')?.dataset.active).toBe('true')
      expect(tab('对话')?.dataset.active).toBe('false')
      // 目录是宿主的事：面板连 limit 都不自己定，全按宿主的默认来。
      expect(bridge.request).toHaveBeenCalledWith('novels/list', {})
    })

    it('says the directory is not there yet instead of painting a failure', async () => {
      installBridge({
        request: host({
          'novels/list': {
            ok: true,
            result: {
              dir: novelDir,
              exists: false,
              matched: 0,
              returned: 0,
              truncated: false,
              novels: []
            }
          }
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openNovels()

      expect(hintLine().textContent).toContain('还没有原文目录')
      expect(hintLine().textContent).toContain(novelDir)
      expect(hintLine().getAttribute('data-tone'), '目录没建不是出错').toBe('info')
      expect(document.getElementById(NOVEL_LIST_ID)?.textContent).toContain('还没有原文')
    })

    it('lists the directory and pages through one novel by character offset', async () => {
      const bridge = installBridge({
        request: host({
          'novels/list': listing([
            novelRow(),
            novelRow({ name: '封面.png', bytes: 900, text: false })
          ]),
          'novels/read': (_method: string, params: unknown) =>
            (params as { offset: number }).offset === 0
              ? {
                  ok: true,
                  result: {
                    name: '长夜.txt',
                    offset: 0,
                    chars: 4000,
                    requested_chars: 4000,
                    total_chars: 9000,
                    at_end: false,
                    bytes: 2048,
                    mtime: 1758900000,
                    encoding: 'utf-8',
                    text: '第一章 雪'
                  }
                }
              : {
                  ok: true,
                  result: {
                    name: '长夜.txt',
                    offset: 4000,
                    chars: 4000,
                    requested_chars: 4000,
                    total_chars: 9000,
                    at_end: true,
                    bytes: 2048,
                    mtime: 1758900000,
                    encoding: 'gb18030',
                    text: '第二章 火'
                  }
                }
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openNovels()

      expect(document.querySelectorAll(`#${NOVEL_LIST_ID} .cs-novel-row`)).toHaveLength(2)
      expect(lineButton('封面.png', '读')?.disabled, '不是 txt/md：照列，但读不了').toBe(true)

      lineButton('长夜.txt', '读')?.click()
      await flush()

      // 分页按**字符**，一页多少字由宿主定：面板不传 chars（宿主的 DEFAULT_READ_CHARS 说了算），
      // 也不去猜宿主的一页是多大 —— 猜了就得靠两边对齐，而那种错是静默的。
      expect(bridge.request).toHaveBeenCalledWith('novels/read', {
        name: '长夜.txt',
        offset: 0
      })
      expect(view(NOVEL_READER_ID).textContent).toBe('第一章 雪')
      expect(button(NOVEL_PAGER_ID, '上一页')?.disabled, '第一页没有上一页').toBe(true)
      expect(view(NOVEL_PAGER_ID).textContent).toContain('第 0–4000 字 / 共 9000 字')
      expect(hintLine().textContent, 'UTF-8 是默认档，不用挂在脸上').not.toContain('utf-8')
      expect(novelLine('长夜.txt')?.getAttribute('data-open'), '在读的那一行要看得出来').toBe('true')

      button(NOVEL_PAGER_ID, '下一页')?.click()
      await flush()

      expect(bridge.request).toHaveBeenCalledWith('novels/read', {
        name: '长夜.txt',
        offset: 4000
      })
      expect(view(NOVEL_READER_ID).textContent).toBe('第二章 火')
      expect(hintLine().textContent, '宿主替你认了 GB18030，这件事要写在脸上').toContain('gb18030')
      expect(hintLine().textContent).toContain('已到末尾')
      expect(button(NOVEL_PAGER_ID, '下一页')?.disabled, '到头了就别再给一个能点的下一页').toBe(
        true
      )
      expect(novelCalls(bridge, 'novels/read'), '禁用的按钮点不动，别再问一遍宿主').toHaveLength(2)

      // 上一页要按**页长**退（宿主的 requested_chars），不是按这一页的正文长度：末页比一页短，
      // 拿正文长度退回去会退不够，"上一页"就落在半中间。
      button(NOVEL_PAGER_ID, '上一页')?.click()
      await flush()

      expect(bridge.request).toHaveBeenCalledWith('novels/read', {
        name: '长夜.txt',
        offset: 0
      })
      expect(view(NOVEL_READER_ID).textContent).toBe('第一章 雪')
    })

    it('puts the host reason where it can be read, and keeps the file listed', async () => {
      const bridge = installBridge({
        request: host({
          'novels/list': listing([novelRow()]),
          'novels/read': {
            ok: false,
            error: {
              code: -32603,
              message: '长夜.txt 认不出编码：试过 utf-8（第 12 字节起）与 gb18030 都不成'
            }
          }
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openNovels()

      lineButton('长夜.txt', '读')?.click()
      await flush()

      // 原因（一整段）放正文区；状态行只说是哪一篇 —— 一行里塞一整段谁也读不完。
      expect(view(NOVEL_READER_ID).textContent).toContain('认不出编码')
      expect(hintLine().textContent).toContain('读不了 长夜.txt')
      expect(hintLine().getAttribute('data-tone')).toBe('error')
      expect(
        document.querySelectorAll(`#${NOVEL_LIST_ID} .cs-novel-row`),
        '读不了不是"这一篇不在"，列表照旧'
      ).toHaveLength(1)
      expect(novelCalls(bridge, 'novels/list')).toHaveLength(1)
    })

    it('asks before replacing a novel that is already in the directory', async () => {
      const bridge = installBridge({
        request: host({
          'novels/list': listing([]),
          'novels/import': (_method: string, params: unknown) =>
            (params as { overwrite: boolean }).overwrite
              ? {
                  ok: true,
                  result: {
                    imported: true,
                    overwritten: true,
                    name: '长夜.txt',
                    bytes: 4096,
                    created_dir: false
                  }
                }
              : {
                  ok: true,
                  result: {
                    imported: false,
                    reason: 'exists',
                    name: '长夜.txt',
                    bytes: 2048,
                    message: '原文目录里已经有 长夜.txt 了（2048 字节）：要换成你这份就带 overwrite 再来一次'
                  }
                }
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openNovels()

      button(NOVEL_VIEW_ID, '导入…')?.click()
      pathInput().value = 'D:/books/长夜.txt'
      button(NOVEL_FORM_ID, '导入')?.click()
      await flush()

      expect(bridge.request).toHaveBeenCalledWith('novels/import', {
        path: 'D:/books/长夜.txt',
        overwrite: false
      })
      expect(hintLine().textContent, '同名不是出错，是要你确认一下').toContain('已经有')
      expect(hintLine().getAttribute('data-tone')).toBe('info')
      expect(button(NOVEL_FORM_ID, '覆盖导入')?.style.display, '这时候才把它露出来').not.toBe(
        'none'
      )

      // 换了路径就把那一下收回去：它只该对着刚问过的那份文件。
      pathInput().value = 'D:/books/另一本.txt'
      pathInput().dispatchEvent(new Event('input'))
      expect(button(NOVEL_FORM_ID, '覆盖导入')?.style.display).toBe('none')
    })

    it('replaces it once the user says so, and says which one changed', async () => {
      const bridge = installBridge({
        request: host({
          'novels/list': listing([novelRow()]),
          'novels/read': {
            ok: true,
            result: {
              name: '长夜.txt',
              offset: 0,
              chars: 4000,
              requested_chars: 4000,
              total_chars: 20,
              at_end: true,
              bytes: 2048,
              mtime: 1758900000,
              text: '旧的那一章'
            }
          },
          'novels/import': {
            ok: true,
            result: {
              imported: true,
              overwritten: true,
              name: '长夜.txt',
              bytes: 4096,
              created_dir: true
            }
          }
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openNovels()

      // 先把要覆盖的那篇打开：覆盖之后正文区必须收掉，不能留着旧的字。
      lineButton('长夜.txt', '读')?.click()
      await flush()
      expect(view(NOVEL_READER_ID).textContent).toBe('旧的那一章')

      button(NOVEL_VIEW_ID, '导入…')?.click()
      pathInput().value = 'D:/books/长夜.txt'
      button(NOVEL_FORM_ID, '覆盖导入')?.click()
      await flush()

      expect(bridge.request).toHaveBeenCalledWith('novels/import', {
        path: 'D:/books/长夜.txt',
        overwrite: true
      })
      expect(hintLine().textContent).toContain('换成了 长夜.txt')
      expect(hintLine().textContent, '顺手把目录建出来这件事也要说出口').toContain(
        '原文目录是这一下建出来的'
      )
      expect(pathInput().value, '导完就清空，免得手一抖再点一次').toBe('')
      expect(novelCalls(bridge, 'novels/list'), '导进来一本，列表要重新列一遍').toHaveLength(2)
      expect(
        view(NOVEL_READER_ID).textContent,
        '正文被换掉了，旧的字不能还挂在屏幕上'
      ).toBe('选中上面一篇，正文显示在这里。')
      expect(novelLine('长夜.txt')?.getAttribute('data-open')).toBeNull()
    })

    it('deletes only on a second click, and only that row', async () => {
      const bridge = installBridge({
        request: host({
          'novels/list': listing([novelRow(), novelRow({ name: '另一本.md', bytes: 1024 })]),
          'novels/delete': { ok: true, result: { name: '长夜.txt', bytes: 2048, deleted: true } }
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openNovels()

      lineButton('长夜.txt', '删除')?.click()

      expect(novelCalls(bridge, 'novels/delete'), '第一下只是把它武装起来').toHaveLength(0)
      expect(lineButton('长夜.txt', '确认删除')).not.toBeNull()
      expect(lineButton('另一本.md', '删除'), '这一下只对着刚点的那一行').not.toBeNull()

      lineButton('长夜.txt', '确认删除')?.click()
      await flush()

      expect(bridge.request).toHaveBeenCalledWith('novels/delete', { name: '长夜.txt' })
      expect(hintLine().textContent).toContain('删掉了 长夜.txt')
      expect(novelCalls(bridge, 'novels/list'), '删完要重新列，别让人对着已经不存在的名字点').toHaveLength(
        2
      )
    })

    it('hands a novel to the conversation without sending it for the user', async () => {
      const bridge = installBridge({ request: host({ 'novels/list': listing([novelRow()]) }) })
      setupDom()
      new Function(script)()
      await openPanel()
      await openNovels()

      lineButton('长夜.txt', '拿去对话')?.click()

      expect(view(CHAT_VIEW_ID).style.display).toBe('flex')
      expect(view(NOVEL_VIEW_ID).style.display).toBe('none')
      const input = document.getElementById(INPUT_ID) as HTMLTextAreaElement
      expect(input.value).toBe('用原文「长夜.txt」开工')
      expect(novelCalls(bridge, 'agent/chat'), '发不发由用户自己按').toHaveLength(0)
    })
  })
})
