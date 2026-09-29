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
const SESSION_RESET_ID = 'comfy-desktop-studio-chat-session-reset'
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
const NOVEL_SIDE_ID = 'comfy-desktop-studio-novel-side'
const NOVEL_SIDE_LIST_ID = 'comfy-desktop-studio-novel-side-list'
const NOVEL_SEARCH_ID = 'comfy-desktop-studio-novel-search'
const NOVEL_TOC_ID = 'comfy-desktop-studio-novel-toc'
const NOVEL_TOC_BACK_ID = 'comfy-desktop-studio-novel-toc-back'
const QUOTE_BAR_ID = 'comfy-desktop-studio-quote-bar'
const VIEWS_ID = 'comfy-desktop-studio-views'
const VIEWS_TITLE_ID = 'comfy-desktop-studio-views-title'
const VIEWS_BACK_ID = 'comfy-desktop-studio-views-back'
const PROJECT_VIEW_ID = 'comfy-desktop-studio-project-view'
const PIPELINE_VIEW_ID = 'comfy-desktop-studio-pipeline-view'
const PIPELINE_HINT_ID = 'comfy-desktop-studio-pipeline-hint'
const PIPELINE_OVERVIEW_ID = 'comfy-desktop-studio-pipeline-overview'
const PIPELINE_LIST_ID = 'comfy-desktop-studio-pipeline-list'
const PIPELINE_PROJECT_ID = 'comfy-desktop-studio-pipeline-project'
const PIPELINE_FORM_ID = 'comfy-desktop-studio-pipeline-form'
const PIPELINE_FORM_TEXT_ID = 'comfy-desktop-studio-pipeline-form-text'
const PIPELINE_FROM_ID = 'comfy-desktop-studio-pipeline-from'
const PIPELINE_TO_ID = 'comfy-desktop-studio-pipeline-to'
const PIPELINE_FORCE_ID = 'comfy-desktop-studio-pipeline-force'
const PROJECT_HINT_ID = 'comfy-desktop-studio-project-hint'
const PROJECT_FORM_ID = 'comfy-desktop-studio-project-form'
const PROJECT_FORM_NAME_ID = 'comfy-desktop-studio-project-form-name'
const PROJECT_FORM_EPISODES_ID = 'comfy-desktop-studio-project-form-episodes'
const PROJECT_FORM_NOVEL_ID = 'comfy-desktop-studio-project-form-novel'
const PROJECT_FORM_UPGRADE_ID = 'comfy-desktop-studio-project-form-upgrade'
const PROJECT_LIST_ID = 'comfy-desktop-studio-project-list'
const PROJECT_HEAD_ID = 'comfy-desktop-studio-project-head'
const PROJECT_SHELVES_ID = 'comfy-desktop-studio-project-shelves'
const PROJECT_READER_ID = 'comfy-desktop-studio-project-reader'
const PROJECT_PAGER_ID = 'comfy-desktop-studio-project-pager'
const PROJECT_FIND_ID = 'comfy-desktop-studio-project-find'
const PROJECT_FIND_COUNT_ID = 'comfy-desktop-studio-project-find-count'
const PROJECT_OVERVIEW_ID = 'comfy-desktop-studio-project-overview'
const PROJECT_FILE_FIND_ID = 'comfy-desktop-studio-project-file-find'
const PROJECT_FILE_FIND_COUNT_ID = 'comfy-desktop-studio-project-file-find-count'
const PROJECT_FILE_FIND_PREV_ID = 'comfy-desktop-studio-project-file-find-prev'
const PROJECT_FILE_FIND_NEXT_ID = 'comfy-desktop-studio-project-file-find-next'
const PROJECT_FILE_FIND_CLEAR_ID = 'comfy-desktop-studio-project-file-find-clear'
const SKILL_ID = 'comfy-desktop-studio-chat-skill'
const SKILL_RUN_ID = 'comfy-desktop-studio-chat-skill-run'
const RENDER_ID = 'comfy-desktop-studio-chat-render'
const RENDER_RUN_ID = 'comfy-desktop-studio-chat-render-run'
const RENDER_ARGS_ID = 'comfy-desktop-studio-chat-render-args'
const RENDER_ARG_PREFIX = 'comfy-desktop-studio-chat-render-arg-'
const RENDER_IMAGES_ID = 'comfy-desktop-studio-chat-render-images'
const WORKFLOW_ID = 'comfy-desktop-studio-chat-workflow'
const WORKFLOW_EDIT_ID = 'comfy-desktop-studio-chat-workflow-edit'
const WORKFLOW_NEW_ID = 'comfy-desktop-studio-chat-workflow-new'
const FIND_ID = 'comfy-desktop-studio-chat-find'
const FIND_COUNT_ID = 'comfy-desktop-studio-chat-find-count'
const FIND_PREV_ID = 'comfy-desktop-studio-chat-find-prev'
const FIND_NEXT_ID = 'comfy-desktop-studio-chat-find-next'
const FIND_CLEAR_ID = 'comfy-desktop-studio-chat-find-clear'
const NOVEL_BATCH_ID = 'comfy-desktop-studio-novel-batch'
const NOVEL_BATCH_ALL_ID = 'comfy-desktop-studio-novel-batch-all'
const NOVEL_BATCH_NONE_ID = 'comfy-desktop-studio-novel-batch-none'
const NOVEL_BATCH_DELETE_ID = 'comfy-desktop-studio-novel-batch-delete'
const WORKBENCH_VIEW_ID = 'comfy-desktop-studio-workbench-view'
const WORKBENCH_HINT_ID = 'comfy-desktop-studio-workbench-hint'
const WORKBENCH_OVERVIEW_ID = 'comfy-desktop-studio-workbench-overview'
const WORKBENCH_PROJECT_ID = 'comfy-desktop-studio-workbench-project'
const WORKBENCH_STEPS_ID = 'comfy-desktop-studio-workbench-steps'
const WORKBENCH_DETAIL_ID = 'comfy-desktop-studio-workbench-detail'
const WORKBENCH_READER_ID = 'comfy-desktop-studio-workbench-reader'
const WORKBENCH_EDIT_ID = 'comfy-desktop-studio-workbench-edit'
const WORKBENCH_SAVE_ID = 'comfy-desktop-studio-workbench-save'
const WORKBENCH_SAVE_HINT_ID = 'comfy-desktop-studio-workbench-save-hint'

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

  /**
   * Catalog the picker reads on open; a per-method stub can override it.
   *
   * 宿主 agent/models 的形状是**按来源分组**的：`groups` 里一组一条源，下拉里 option 的值
   * 是「来源::模型名」（换源等于换地址+密钥，只发模型名会把请求发去错的那一家）。顶层的
   * `models` / `source` / `error` 说的仍是主源那一组，宿主照样发着，这里一并给全。
   */
  const catalog = (models: string[], current: string, error: string | null = null): unknown => ({
    ok: true,
    result: {
      current,
      current_source: 'default',
      models,
      source: error ? 'config' : 'endpoint',
      error,
      groups: [
        {
          source: 'default',
          label: '127.0.0.1:11434',
          models,
          origin: error ? 'config' : 'endpoint',
          error
        }
      ],
      extra_error: null
    }
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

  /**
   * 面板的事件订阅挂了**两份**：对话那条（onEvent）与流水线那条（onPipelineEvent，见 start）——
   * 后者不能挂进前者，因为 onEvent 头一句就是"没有一轮在跑就直接丢"。所以这个桩得把事件喂给
   * **所有**注册者：只记最后一条的话，后挂的那份会把前一份挤掉，跑起来活像"对话再也收不到
   * 宿主的通知"，而真正的原因在测试桩里，不在被测代码里。
   */
  const installBridge = (
    overrides: { status?: unknown; request?: unknown | RequestStub } = {}
  ): StudioBridge => {
    const listeners: Array<(payload: unknown) => void> = []
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
            : (overrides.request ?? { ok: true, result: { text: '答案在此' } })
        )
      ),
      onEvent: vi.fn((callback: (payload: unknown) => void) => {
        listeners.push(callback)
        emit = (payload: unknown): void => {
          listeners.forEach((listener) => listener(payload))
        }
        return vi.fn(() => {
          const at = listeners.indexOf(callback)
          if (at >= 0) listeners.splice(at, 1)
        })
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

  // 用户那一行里躺着两个按钮（复制 / 改一下，见面板 userActions）：说"这个气泡里说的话是哪句"，
  // 得先把动作条摘掉 —— 不摘读到的是「复制改一下」缀在话尾巴上。面板自己也这么摘
  // （findRowText）。
  const saidOf = (row: Element | null | undefined): string => {
    if (!row) return ''
    const copy = row.cloneNode(true) as Element
    copy.querySelector('.cs-user-actions')?.remove()
    return copy.textContent ?? ''
  }
  const said = (kind: string): string[] => rows(kind).map((row) => saidOf(row))

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

  it('keeps the backslashes the injected regexes need', () => {
    // 这一段 JS 住在 TS 模板字符串里：源码里写 `\s`，注入前会被模板那层先吃掉、变成字面的 s，
    // 所以反斜杠要写两遍（这个坑踩过几回，见脚本里那几处注释）。这里把出图落点那两个正则钉死：
    // 少写一遍的话 `[\\/]` 会退化成只匹配正斜杠 —— Windows 路径那道判断就形同虚设，
    // 而它挡的是"把图落进一个拼歪的目录"这种不报错的错。
    expect(script).toContain("replace(/[\\\\/]+$/, '')")
    expect(script).toContain('/^[a-zA-Z]:[\\\\/]/')
    expect(script).not.toContain("replace(/[\\/]+$/, '')")
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
    // 两份：对话一份、流水线一份（见 start）。流水线那份不能挂在对话那份里 ——
    // onEvent 头一句是"没有一轮在跑就直接丢"，而流水线跑起来时对话那边根本没在跑。
    expect(bridge.onEvent).toHaveBeenCalledTimes(2)
    bridge.onEvent.mock.results.forEach((entry, at) => {
      expect(typeof entry.value, '第 ' + (at + 1) + ' 份订阅得能单独退掉').toBe('function')
    })
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
    expect(said('user')).toEqual(['帮我把这张图放大两倍'])
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
    expect(rows('assistant').map((r) => r.textContent)).toEqual([
      '先查一下可用的 skill',
      '答案在此'
    ])
    expect(rows('assistant')[0]?.getAttribute('data-variant')).toBe('intermediate')
    expect(rows('assistant')[1]?.getAttribute('data-variant')).toBe('final')
  })

  it('counts the wait, and says when the host is retrying the model call', async () => {
    installBridge({
      request: (method: string) =>
        method === 'agent/chat' ? new Promise(() => {}) : { ok: true, result: { text: '答案在此' } }
    })
    setupDom()
    new Function(script)()
    await openPanel()

    await send('问一句')
    expect(said('pending')[0]).toContain('已等待 0s')

    // 宿主在一次模型调用失败后会报 retry（见 lib/comfy_studio/agent/loop.py 的 report_retry）。
    // 那是"还活着、只是还没成"的唯一信号，原先面板不认这个类型 —— 于是它和卡死长得一模一样。
    emit({
      params: {
        session_id: 'default',
        type: 'retry',
        attempt: 2,
        total: 5,
        delay: 4,
        reason: '500'
      }
    })
    await flush()

    expect(said('pending')[0]).toContain('模型没回应，4s 后重试')
    expect(said('pending')[0]).toContain('第 2/5 次')
    expect(document.getElementById(STATUS_ID)?.textContent).toContain('重试')

    await vi.advanceTimersByTimeAsync(3000)
    expect(said('pending')[0], 'the wait keeps ticking while the model retries').toContain(
      '已等待 3s'
    )
  })

  it('offers a way out when a turn has been silent for too long', async () => {
    installBridge({
      request: (method: string) =>
        method === 'agent/chat' ? new Promise(() => {}) : { ok: true, result: { text: '答案在此' } }
    })
    setupDom()
    new Function(script)()
    await openPanel()

    await send('问一句')
    const sendButton = document.getElementById(SEND_ID) as HTMLButtonElement
    expect(sendButton.disabled, 'a turn in flight holds the composer').toBe(true)

    // 这颗按钮是**提示**不是判负：宿主那一轮还攥着这个会话，自动解锁只会让下一句撞上
    // "会话已有一轮在跑"（见 lib/comfy_studio/server.py 的 agent_chat）。所以要不要放开，
    // 由用户自己按 —— 但门得摆在那儿，不能让面板永远等下去。
    const escapeButton = (): HTMLButtonElement | null =>
      document.querySelector(`#${LOG_ID} .cs-force-reset`)

    await vi.advanceTimersByTimeAsync(299_000)
    expect(escapeButton(), 'not yet: five minutes of silence is the threshold').toBeNull()

    await vi.advanceTimersByTimeAsync(2000)
    const escape = escapeButton()
    expect(escape, 'silence long enough earns a way out').not.toBeNull()

    escape?.click()
    await flush()
    await flush()

    expect(sendButton.disabled, 'the way out really hands the composer back').toBe(false)
    expect(rows('pending')).toHaveLength(0)
    expect(said('error').join(''), 'it must say the host may still be running').toContain(
      '宿主那一轮可能还在跑'
    )

    // 复位只放开面板：宿主那一轮还占着这个会话。原先收尾把"停止"键一起摘掉了（busy 清零 +
    // display:none），于是同一句文案让用户去点一个已经消失的键，用户只剩"发一句被拒一次"
    // 这条路 —— 键得留下来，而且要说清它现在停的是谁（见 setStopVisible / cancelTurn）。
    const stopButton = document.getElementById(STOP_ID) as HTMLButtonElement
    expect(stopButton.style.display, 'the host turn is still out there').not.toBe('none')
    expect(stopButton.textContent).toBe('叫停宿主那一轮')
  })

  it('really cancels the host turn from that key after a force reset', async () => {
    const request = vi.fn((method: string) => {
      if (method === 'agent/models') return catalog(['a:3b'], 'a:3b')
      if (method === 'agent/cancel') {
        return { ok: true, result: { session_id: 'default', cancelled: true } }
      }
      return new Promise(() => {}) // 这一轮一直挂着：面板与宿主各有一份"还在跑"
    })
    installBridge({ request })
    setupDom()
    new Function(script)()
    await openPanel()

    await send('问一句')
    await vi.advanceTimersByTimeAsync(301_000)
    const escape = document.querySelector(`#${LOG_ID} .cs-force-reset`) as HTMLButtonElement
    escape.click()
    await flush()
    await flush()

    const stop = document.getElementById(STOP_ID) as HTMLButtonElement
    stop.click()
    await flush()

    // 面板这边 busy 已经是 false 了，可发的还是得发：那一轮在宿主手里，只有它能收。
    expect(request).toHaveBeenCalledWith('agent/cancel', { session_id: 'default' })
    expect(document.getElementById(STATUS_ID)?.textContent).toContain('正在叫停宿主那一轮')
  })

  it('offers to cancel the host turn when the host rejects a second turn', async () => {
    // 复位之后用户多半会先试一句（"继续"），宿主回 -32602。那时面板要是只报一行"失败"，
    // 用户就只能再发一次 —— 得把能停那一轮的东西摆出来。
    const request = vi.fn((method: string) => {
      if (method === 'agent/models') return catalog(['a:3b'], 'a:3b')
      if (method === 'agent/chat') {
        return {
          ok: false,
          error: {
            code: -32602,
            message: '会话 s1 已有一轮在跑；等它结束、agent/cancel 掉它，或换个 session_id'
          }
        }
      }
      return { ok: true, result: {} }
    })
    installBridge({ request })
    setupDom()
    new Function(script)()
    await openPanel()

    await send('接着说')

    const stop = document.getElementById(STOP_ID) as HTMLButtonElement
    expect(stop.style.display, 'the host still holds this session').not.toBe('none')
    expect(stop.textContent).toBe('叫停宿主那一轮')
    expect(said('error').join('')).toContain('已有一轮在跑')
    expect(document.getElementById(STATUS_ID)?.textContent).toContain('还在跑')
    // 话也没吞：还回输入框了，换个会话就能发。
    expect((document.getElementById(INPUT_ID) as HTMLTextAreaElement).value).toBe('接着说')

    stop.click()
    await flush()

    expect(request).toHaveBeenCalledWith('agent/cancel', { session_id: 'default' })
  })

  describe('coming back to an older conversation', () => {
    /** 只有 `agent/history` 走自己的桩：开抽屉时面板还会问模型目录，那些保持默认。 */
    const archive =
      (result: unknown): RequestStub =>
      (method) =>
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
      expect(said('user')).toEqual(['帮我把这张图放大两倍'])
      expect(rows('assistant').map((r) => r.textContent)).toEqual([
        '先查一下可用的 skill',
        '已经好了'
      ])
      expect(rows('assistant')[0]?.getAttribute('data-variant')).toBe('intermediate')
      expect(rows('assistant')[1]?.getAttribute('data-variant')).toBe('final')
      // 工具卡是同一套画法：结果按 id 配回调用那张，不另起一行
      expect(rows('tool')).toHaveLength(1)
      expect(rows('tool')[0]?.getAttribute('data-tool')).toBe('fake__do_it')
      expect(rows('tool')[0]?.getAttribute('data-state')).toBe('done')
    })

    it('says how many older messages the archive could not keep', async () => {
      installBridge({
        request: archive(
          archived({ dropped: 12, entries: [{ type: 'user', text: '很久以前问的' }] })
        )
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
        request: archive({
          ok: false,
          error: { code: -32603, message: '对话存档读不了（x.json）：坏了' }
        })
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
      expect(said('user')).toEqual(['上次问的', '这一轮问的'])
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

    const host =
      (sessions: unknown, over: { history?: unknown } = {}): RequestStub =>
      (method: string) => {
        if (method === 'agent/sessions')
          return { ok: true, result: { sessions, live: 1, max_sessions: 8 } }
        if (method === 'agent/history') return over.history ?? { ok: true, result: { entries: [] } }
        return { ok: true, result: { text: '答案在此' } }
      }

    const picker = (): HTMLSelectElement => document.getElementById(SESSION_ID) as HTMLSelectElement
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
      expect(said('user')).toEqual(['这张图放大两倍'])

      picker().value = 'chat-2'
      picker().dispatchEvent(new Event('change'))
      await flush()

      expect(state().session).toBe('chat-2')
      const asked = bridge.request.mock.calls.filter((call) => call[0] === 'agent/history')
      expect(asked[asked.length - 1]).toEqual(['agent/history', { session_id: 'chat-2' }])
      expect(said('user')).toEqual(['赛博朋克海报'])
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
      expect(said('user')).toEqual(['这是 default 的话'])

      picker().value = 'chat-3'
      picker().dispatchEvent(new Event('change'))
      await flush()
      picker().value = 'chat-2'
      picker().dispatchEvent(new Event('change'))
      await flush()
      expect(state().session).toBe('chat-2')
      expect(said('user')).toEqual(['这是 chat-2 的话'])

      // 迟到的 chat-3 现在回来了：不许画。
      parked.forEach((resolve) =>
        resolve({ ok: true, result: { entries: [{ type: 'user', text: '这是 chat-3 的话' }] } })
      )
      await flush()
      expect(said('user')).toEqual(['这是 chat-2 的话'])
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
      expect(said('user')).toEqual(['关掉前说的话'])
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
          method === 'agent/sessions'
            ? { ok: true, result: { sessions: [row()] } }
            : { ok: true, result: { text: '答案在此' } }
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

    it('clears this conversation only after a second click, and says what it erased', async () => {
      const bridge = installBridge({
        request: (method: string): unknown => {
          if (method === 'agent/reset') {
            return {
              ok: true,
              result: { session_id: 'default', reset: true, history_cleared: true }
            }
          }
          return { ok: true, result: { text: '答案在此' } }
        }
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await send('这句待会儿要被清掉')

      const reset = document.getElementById(SESSION_RESET_ID) as HTMLButtonElement
      expect(reset.textContent, '跟「关掉」并排，得让人一眼分得清').toBe('清空')

      reset.click()
      await flush()

      // 第一下只是问一句：清空连存档一起抹，撤不回来。
      expect(
        bridge.request.mock.calls.filter((call) => call[0] === 'agent/reset'),
        '还只是问了一句'
      ).toHaveLength(0)
      expect(document.getElementById(STATUS_ID)?.textContent).toContain('撤不回来')
      expect(rows('user'), '没真清之前屏上的话一个字都不能少').toHaveLength(1)

      reset.click()
      await flush()

      expect(bridge.request).toHaveBeenCalledWith('agent/reset', { session_id: 'default' })
      // 屏上那些行现在是"已经不存在的话"，留着就是给一段空对话背书。
      expect(rows('user')).toHaveLength(0)
      expect(document.getElementById(STATUS_ID)?.textContent).toBe(
        '已清空这一段：说过的话连存档一起抹掉了'
      )
      expect(rows('error')).toHaveLength(0)
    })

    it('says so when clearing had nothing to erase', async () => {
      installBridge({
        request: (method: string): unknown => {
          if (method === 'agent/reset') {
            return {
              ok: true,
              result: { session_id: 'default', reset: false, history_cleared: false }
            }
          }
          return { ok: true, result: { text: '答案在此' } }
        }
      })
      setupDom()
      new Function(script)()
      await openPanel()

      document.getElementById(SESSION_RESET_ID)?.click()
      await flush()
      document.getElementById(SESSION_RESET_ID)?.click()
      await flush()

      // 两个字段都是 false：内存里没这一段、磁盘上也没东西可删。别报成"已清空"。
      expect(document.getElementById(STATUS_ID)?.textContent).toBe('这一段本来就空着，没什么可清的')
    })

    it('says the archive was the only thing left when history is off', async () => {
      installBridge({
        request: (method: string): unknown => {
          if (method === 'agent/reset') {
            return {
              ok: true,
              result: { session_id: 'default', reset: true, history_cleared: false }
            }
          }
          return { ok: true, result: { text: '答案在此' } }
        }
      })
      setupDom()
      new Function(script)()
      await openPanel()

      document.getElementById(SESSION_RESET_ID)?.click()
      await flush()
      document.getElementById(SESSION_RESET_ID)?.click()
      await flush()

      expect(document.getElementById(STATUS_ID)?.textContent).toBe(
        '已清空这一段：它没有存档，只清了内存里这一份'
      )
    })

    it('reports a failed clear instead of pretending the screen is empty', async () => {
      installBridge({
        request: (method: string): unknown => {
          if (method === 'agent/reset') {
            return { ok: false, error: { code: 'EIO', message: '存档删不掉' } }
          }
          return { ok: true, result: { text: '答案在此' } }
        }
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await send('这句话还在')

      document.getElementById(SESSION_RESET_ID)?.click()
      await flush()
      document.getElementById(SESSION_RESET_ID)?.click()
      await flush()

      expect(document.getElementById(STATUS_ID)?.textContent).toBe('这一段没清掉')
      expect(rows('error')).toHaveLength(1)
      expect(rows('user'), '没清成就不能把屏上的话抹掉').toHaveLength(1)
    })

    it('takes the armed clear back when the drawer is reopened', async () => {
      const bridge = installBridge({
        request: (): unknown => ({
          ok: true,
          result: { session_id: 'default', reset: true, history_cleared: true }
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()

      document.getElementById(SESSION_RESET_ID)?.click()
      await flush()
      await openPanel() // 关
      await openPanel() // 再开

      document.getElementById(SESSION_RESET_ID)?.click()
      await flush()

      expect(
        bridge.request.mock.calls.filter((call) => call[0] === 'agent/reset'),
        '隔了半天再点一下，不该把一段对话清掉'
      ).toHaveLength(0)
      expect(document.getElementById(STATUS_ID)?.textContent).toContain('撤不回来')
    })
  })

  describe('where it keeps things on this machine', () => {
    /** 开抽屉时面板会问几件事（模型目录、上次的对话、host/info）；只有 host/info 走自己的桩。 */
    const hostInfo =
      (result: Record<string, unknown> | null): RequestStub =>
      (method) =>
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
        request: hostInfo({
          ...paths,
          memory: true,
          memory_entries: 3,
          history: true,
          web: true,
          web_backend: 'bing',
          web_search_url: 'https://www.bing.com/search'
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()

      expect(line()?.textContent).toBe('它记着 3 条事；对话存在这台机器上；能联网（走必应）')
      // 路径太长，铺在界面上要占掉半个抽屉：放悬停提示里
      expect(line()?.title).toContain('memory.json')
      expect(line()?.title).toContain('sessions')
      // 搜索走哪条路也一样："搜出来不对"时第一个要看的就是它，界面上没别处会说。
      expect(line()?.title).toContain('bing.com')
    })

    it('names the self-hosted search backend when that is what it is using', async () => {
      installBridge({
        request: hostInfo({
          memory: true,
          history: true,
          web: true,
          web_backend: 'searxng',
          // 宿主走自建实例时**不报**必应那条入口（它根本没被请求过，见 lib/comfy_studio/web.py
          // 那一档的注释）：这里就照真实的形状给 null，走的正是"报什么画什么"这条路。
          web_search_url: null,
          web_searxng_url: 'http://127.0.0.1:8888'
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()

      expect(line()?.textContent).toContain('能联网（自建 SearXNG）')
      expect(line()?.title, '自建实例地址是排障要看的那一眼').toContain('127.0.0.1:8888')
      // 入口这时就是那个自建实例：不该再冒出一句必应，否则两句互相打架、用户照错的那句去查。
      expect(line()?.title ?? '').not.toContain('搜索入口')
    })

    it('says out loud when the host was started without web access', async () => {
      installBridge({ request: hostInfo({ memory: true, history: true, web: false }) })
      setupDom()
      new Function(script)()
      await openPanel()

      expect(line()?.textContent).toContain('这次没开联网（--no-web）')
      // 关了就关干净：没有搜索入口这种话不该出现，那会让用户以为还能搜。
      expect(line()?.title ?? '').not.toContain('搜索入口')
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
      installBridge({ request: hostInfo({ memory: false, history: false, web: false }) })
      setupDom()
      new Function(script)()
      await openPanel()

      expect(line()?.textContent).toBe(
        '这次没开记忆（--no-memory），你说过的事它不会记住；' +
          '这次没开对话存档（--no-history），面板一关这段对话就没了；' +
          '这次没开联网（--no-web），不知道的事它只能凭记忆答'
      )
    })

    it('does not guess at fields the host did not report', async () => {
      installBridge({ request: hostInfo({}) })
      setupDom()
      new Function(script)()
      await openPanel()

      expect(line()?.textContent).toBe('记忆开没开它没说；对话存不存它没说；联网开没开它没说')
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
            ? {
                ok: true,
                result: {
                  memory: true,
                  memory_entries: entries,
                  history: true,
                  web: true,
                  web_backend: 'bing'
                }
              }
            : { ok: true, result: { text: '答案在此' } }
      })
      setupDom()
      new Function(script)()
      await openPanel()
      expect(line()?.textContent).toBe('还没记住什么；对话存在这台机器上；能联网（走必应）')

      entries = 1 // 这一轮里它记下了一条
      await send('记住我喜欢方形构图')
      await flush() // 这一问是收尾时才发的，多让一拍

      expect(line()?.textContent).toBe('它记着 1 条事；对话存在这台机器上；能联网（走必应）')
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
    expect(card.querySelector('.cs-block')?.textContent, 'arguments are shown').toContain(
      '"limit": 5'
    )

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

    emit({
      params: {
        session_id: 'default',
        type: 'tool_call',
        id: 'call_1',
        name: 'srv__run',
        arguments: {}
      }
    })
    // 宿主把 isError 的结果标成 "ERROR: ..." 文本喂回来（mcp/result.py 的 tool_text）
    emit({
      params: {
        session_id: 'default',
        type: 'tool_result',
        id: 'call_1',
        name: 'srv__run',
        text: 'ERROR: 显存不够'
      }
    })

    expect(rows('tool')[0]?.getAttribute('data-state')).toBe('error')
    expect(rows('tool')[0]?.querySelector('.cs-tool-state')?.textContent).toBe('失败')

    emit({
      params: {
        session_id: 'default',
        type: 'tool_result',
        id: 'call_9',
        name: 'srv__run',
        text: '结果'
      }
    })

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
    emit({
      params: {
        session_id: 'default',
        type: 'tool_call',
        id: 'call_1',
        name: 'srv__run',
        arguments: {}
      }
    })
    emit({
      params: {
        session_id: 'default',
        type: 'tool_result',
        id: 'call_1',
        name: 'srv__run',
        text: long
      }
    })

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
    settleChat({
      ok: true,
      result: { session_id: 'default', text: '', cancelled: true, reason: '用户取消' }
    })
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
    expect(Array.from(picker.options).map((o) => o.value)).toEqual([
      'default::a:3b',
      'default::b:7b'
    ])
    expect(picker.value, 'current model is preselected').toBe('default::b:7b')
    expect(picker.disabled).toBe(false)
  })

  it('keeps each model source in a group of its own, and switches the one that was picked', async () => {
    // 本机 Ollama 与云端 DeepSeek 并列：两串模型名混在一列里，用户分不清哪个要花钱。
    const request = vi.fn((method: string, params: unknown) => {
      if (method === 'agent/models') {
        return {
          ok: true,
          result: {
            current: 'deepseek-v4-pro',
            current_source: 'DeepSeek',
            models: ['qwen2.5:7b'],
            source: 'endpoint',
            error: null,
            groups: [
              {
                source: 'default',
                label: '127.0.0.1:11434',
                models: ['qwen2.5:7b'],
                origin: 'endpoint',
                error: null
              },
              {
                source: 'DeepSeek',
                label: 'DeepSeek',
                models: ['deepseek-v4-pro', 'deepseek-flash'],
                origin: 'endpoint',
                error: null
              }
            ],
            extra_error: null
          }
        }
      }
      if (method === 'agent/model') {
        return {
          ok: true,
          result: {
            model: 'qwen2.5:7b',
            changed: true,
            applied: [],
            skipped: [],
            params
          }
        }
      }
      return { ok: true, result: { text: '答案在此' } }
    })
    installBridge({ request })
    setupDom()
    new Function(script)()
    await openPanel()

    const picker = document.getElementById(MODEL_ID) as HTMLSelectElement
    expect(Array.from(picker.querySelectorAll('optgroup')).map((g) => g.label)).toEqual([
      '127.0.0.1:11434',
      'DeepSeek'
    ])
    expect(Array.from(picker.options).map((o) => o.value)).toEqual([
      'default::qwen2.5:7b',
      'DeepSeek::deepseek-v4-pro',
      'DeepSeek::deepseek-flash'
    ])
    expect(picker.value, 'the model in use is selected, not the first one listed').toBe(
      'DeepSeek::deepseek-v4-pro'
    )

    picker.value = 'default::qwen2.5:7b'
    picker.dispatchEvent(new Event('change'))
    await flush()

    expect(request).toHaveBeenCalledWith('agent/model', { model: 'default::qwen2.5:7b' })
    expect(document.getElementById(STATUS_ID)?.textContent).toContain('qwen2.5:7b')
    expect(picker.value, 'the picker stays on the source that was picked').toBe(
      'default::qwen2.5:7b'
    )
  })

  it('says which source could not hand over a model list, and keeps the others', async () => {
    const request = vi.fn(() => ({
      ok: true,
      result: {
        current: 'a:3b',
        current_source: 'default',
        models: ['a:3b'],
        source: 'endpoint',
        error: null,
        groups: [
          {
            source: 'default',
            label: '127.0.0.1:11434',
            models: ['a:3b'],
            origin: 'endpoint',
            error: null
          },
          {
            source: 'DeepSeek',
            label: 'DeepSeek',
            models: [],
            origin: 'config',
            error: '连不上 https://api.deepseek.com/v1/models: boom'
          }
        ],
        extra_error: null
      }
    }))
    installBridge({ request })
    setupDom()
    new Function(script)()
    await openPanel()

    const picker = document.getElementById(MODEL_ID) as HTMLSelectElement
    expect(
      Array.from(picker.options).map((o) => o.value),
      'the broken source is not dropped'
    ).toEqual(['default::a:3b'])
    // 坏掉的那家照样画在分组里（点不了），标题上写清是它、为什么 —— 悄悄抹掉的话，
    // 用户只会以为自己刚配的那一家没生效，然后反复改它。
    const broken = Array.from(picker.querySelectorAll('optgroup')).find(
      (g) => g.label === 'DeepSeek'
    )
    expect(broken, 'the source that failed is still listed').toBeTruthy()
    expect(broken?.title).toContain('boom')
    expect(picker.title).toContain('DeepSeek')
    expect(picker.title).toContain('没给模型列表')
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
    picker.value = 'default::b:7b'
    picker.dispatchEvent(new Event('change'))
    await flush()

    // 发的是整串：宿主靠它决定换哪条源的地址与密钥
    expect(request).toHaveBeenCalledWith('agent/model', { model: 'default::b:7b' })
    expect(document.getElementById(STATUS_ID)?.textContent).toContain('b:7b')
    expect(picker.value, 'after the switch the picker still knows the source').toBe('default::b:7b')
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
    picker.value = 'default::b:7b'
    picker.dispatchEvent(new Event('change'))
    await flush()

    expect(picker.value, 'selection falls back to the model actually in use').toBe('default::a:3b')
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
    expect(Array.from(picker.options).map((o) => o.value)).toEqual(['default::only:1'])
    // 这份桩是老宿主的形状（没有 groups）：退回主源那一组，组名就是主源的源名。
    // 提示语要说清"是哪一家 + 为什么"，只说其中一半，用户不知道该改地址、改密钥还是重启。
    expect(picker.title).toContain('default')
    expect(picker.title).toContain('没给模型列表')
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
      method === 'agent/models'
        ? catalog(['a:3b'], 'a:3b')
        : { ok: true, result: { text: '答案在此' } }
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
        return agentsCatalog(
          [
            { id: 'general', name: '通用' },
            { id: 'artist', name: '画师' }
          ],
          'general'
        )
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
        return agentsCatalog(
          [
            { id: 'general', name: '通用' },
            { id: 'ghost', name: '幽灵' }
          ],
          'general'
        )
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

  describe('说过的话：复制 / 改一下 / 在这一段里找字', () => {
    const findBox = (): HTMLInputElement => document.getElementById(FIND_ID) as HTMLInputElement
    const findCount = (): HTMLElement => document.getElementById(FIND_COUNT_ID) as HTMLElement
    /** 被标上的行。只有"说过的话"参与，所以工具卡、错误行不在这儿。 */
    const hitRows = (): HTMLElement[] =>
      Array.from(document.querySelectorAll<HTMLElement>(`#${LOG_ID} [data-hit]`))
    const saidRow = (index = 0): Element | undefined => rows('user')[index]
    const actionButton = (text: string, row: Element | undefined = saidRow()): HTMLButtonElement =>
      Array.from(row?.querySelectorAll('button') ?? []).find(
        (b) => b.textContent === text
      ) as HTMLButtonElement
    /** 敲进找字框里（面板听的是 input 事件，不是 change）。 */
    const typeFind = (query: string): void => {
      const box = findBox()
      box.value = query
      box.dispatchEvent(new Event('input'))
    }
    const keyFind = (key: string, shiftKey = false): void => {
      findBox().dispatchEvent(new KeyboardEvent('keydown', { key, shiftKey }))
    }

    it('offers copy and 改一下 on my lines, and only on mine', async () => {
      installBridge()
      setupDom()
      new Function(script)()
      await openPanel()
      await send('帮我起个标题')

      expect(
        Array.from(saidRow()?.querySelectorAll('.cs-user-actions button') ?? []).map(
          (b) => b.textContent
        )
      ).toEqual(['复制', '改一下'])
      // 模型说的话没有"改一下"这回事：宿主没有"改掉某一条历史"的口子（agent/chat 只接一段话）。
      expect(rows('assistant')[0]?.querySelector('.cs-user-actions')).toBeNull()
    })

    it('puts my line back in the composer when I ask to change it', async () => {
      const bridge = installBridge()
      setupDom()
      new Function(script)()
      await openPanel()
      await send('帮我起个标题')

      actionButton('改一下').click()
      await flush()

      expect((document.getElementById(INPUT_ID) as HTMLTextAreaElement).value).toBe('帮我起个标题')
      expect(document.getElementById(STATUS_ID)?.textContent, '得说清这不是改历史').toContain(
        '另起一轮'
      )
      expect(said('user'), '原来那一轮还留在这段对话里').toEqual(['帮我起个标题'])
      expect(
        bridge.request.mock.calls.filter((call: unknown[]) => call[0] === 'agent/chat'),
        '面板不替人把改完的话发出去'
      ).toHaveLength(1)
    })

    describe('把这一段拷到剪贴板', () => {
      afterEach(() => {
        Reflect.deleteProperty(navigator, 'clipboard')
      })

      it('copies the line, and says so on the button for a while', async () => {
        const writeText = vi.fn(() => Promise.resolve())
        Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
        installBridge()
        setupDom()
        new Function(script)()
        await openPanel()
        await send('拷我这一段')

        const copy = actionButton('复制')
        copy.click()
        await flush()

        expect(writeText).toHaveBeenCalledWith('拷我这一段')
        expect(copy.textContent).toBe('已复制')

        await vi.advanceTimersByTimeAsync(2000)
        expect(copy.textContent, '两秒后自己回到「复制」').toBe('复制')
      })

      it('selects the words and says why when the clipboard refuses the write', async () => {
        // 沙箱里的 webview 不许写剪贴板时就是这样：接口在，writeText 直接打回失败。
        const writeText = vi.fn(() => Promise.reject(new Error('NotAllowedError')))
        Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
        installBridge()
        setupDom()
        new Function(script)()
        await openPanel()
        await send('拷我这一段')

        const copy = actionButton('复制')
        copy.click()
        await flush()

        expect(writeText).toHaveBeenCalledWith('拷我这一段')
        expect(copy.textContent, '没拷上就不许说「已复制」').toBe('复制')
        expect(document.getElementById(STATUS_ID)?.textContent).toContain('Ctrl+C')
        expect(document.getElementById(STATUS_ID)?.getAttribute('data-tone')).toBe('error')
        // 补救：那一段得真的被选亮，人才按得动 Ctrl+C（选的是话本身，不含动作条）。
        const selection = window.getSelection()
        expect(selection?.rangeCount).toBe(1)
        expect(selection?.getRangeAt(0).toString()).toBe('拷我这一段')
      })
    })

    it('finds a phrase in this conversation, walking and wrapping between the hits', async () => {
      installBridge()
      setupDom()
      new Function(script)()
      await openPanel()
      await send('雪落下来')
      await send('又一场雪')

      typeFind('雪')
      await flush()

      expect(findCount().textContent).toBe('1/2 处')
      expect(hitRows()).toHaveLength(2)
      expect(hitRows()[0]?.dataset.hit).toBe('current')
      expect(hitRows()[1]?.dataset.hit, '命中了但不是当前那一处').toBe('true')

      document.getElementById(FIND_NEXT_ID)?.click()
      expect(findCount().textContent).toBe('2/2 处')
      expect(hitRows()[1]?.dataset.hit).toBe('current')

      document.getElementById(FIND_NEXT_ID)?.click()
      expect(findCount().textContent, '到最后一处再往下就绕回第一处').toBe('1/2 处')

      document.getElementById(FIND_PREV_ID)?.click()
      expect(findCount().textContent, '在第一处往上就绕回最后一处').toBe('2/2 处')

      keyFind('Enter')
      expect(findCount().textContent).toBe('1/2 处')
      keyFind('Enter', true)
      expect(findCount().textContent).toBe('2/2 处')

      document.getElementById(FIND_CLEAR_ID)?.click()
      expect(findCount().textContent).toBe('')
      expect(hitRows(), '清空时标记一起摘掉').toHaveLength(0)
      expect(findBox().value).toBe('')

      typeFind('没这一串字')
      expect(findCount().textContent).toBe('没找到')
      expect(findCount().dataset.tone).toBe('error')

      keyFind('Escape')
      expect(findBox().value).toBe('')
      expect(findCount().textContent).toBe('')
    })

    it('searches what was said, not the buttons on the line', async () => {
      installBridge()
      setupDom()
      new Function(script)()
      await openPanel()
      await send('随便一句')

      // 每一行自己那条动作条上就写着"复制"，连它一起找的话每一行都会命中。
      typeFind('复制')

      expect(findCount().textContent).toBe('没找到')
    })

    it('counts the hits again when the conversation grows', async () => {
      installBridge()
      setupDom()
      new Function(script)()
      await openPanel()
      await send('雪落下来')

      typeFind('雪')
      expect(findCount().textContent).toBe('1/1 处')

      await send('又一场雪')

      expect(findCount().textContent, '刚发的那一句也得算进来').toBe('1/2 处')
      expect(hitRows()).toHaveLength(2)
    })

    it('puts the failed round back in the composer', async () => {
      installBridge({ request: { ok: false, error: { code: -32603, message: '模型没配' } } })
      setupDom()
      new Function(script)()
      await openPanel()

      await send('这句话别丢')

      expect(rows('error')).toHaveLength(1)
      expect((document.getElementById(INPUT_ID) as HTMLTextAreaElement).value).toBe('这句话别丢')
      expect(document.getElementById(STATUS_ID)?.textContent).toContain('还回输入框')
      expect(document.getElementById(STATUS_ID)?.getAttribute('data-tone')).toBe('error')
    })

    it('leaves what I have typed since alone when a slow round fails', async () => {
      let fail: (value: unknown) => void = () => {}
      installBridge({
        request: (method: string): unknown =>
          method === 'agent/chat'
            ? new Promise((resolve) => {
                fail = resolve
              })
            : { ok: true, result: { text: '答案在此' } }
      })
      setupDom()
      new Function(script)()
      await openPanel()

      const input = document.getElementById(INPUT_ID) as HTMLTextAreaElement
      input.value = '第一句'
      document.getElementById(SEND_ID)?.click()
      await flush()

      input.value = '我已经在写第二句了'
      fail({ ok: false, error: { message: '宿主忙' } })
      await flush()

      expect(input.value, '覆盖掉刚写的更糟，那就一个字都别动').toBe('我已经在写第二句了')
      expect(document.getElementById(STATUS_ID)?.textContent).toBe('这一轮失败了')
    })
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
    const host =
      (handlers: Record<string, unknown>): RequestStub =>
      (method, params) =>
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

    const sideList = (): HTMLElement => view(NOVEL_SIDE_LIST_ID)
    const sideRows = (): HTMLElement[] =>
      Array.from(
        document.querySelectorAll<HTMLElement>(`#${NOVEL_SIDE_LIST_ID} .cs-novel-side-row`)
      )
    /** 第几行。列表里没有那么多行时直接炸出来 —— 断言里少了一行不该静默地变成 undefined。 */
    const sideRow = (index: number): HTMLElement => {
      const row = sideRows()[index]
      if (!row) throw new Error(`左栏里没有第 ${index} 行`)
      return row
    }
    /** 一行里第一个 span 是标题（搜索结果那几行没有 span：整行就是一段上下文）。 */
    const sideTitles = (): (string | null)[] =>
      sideRows().map((row) => row.querySelector('span')?.textContent ?? null)

    /** 宿主 novels/chapters 的回包：两章。第二段从第 5000 字起 —— 跳章跳的就是这个数。 */
    const chapterList = (over: Record<string, unknown> = {}): unknown => ({
      ok: true,
      result: {
        name: '长夜.txt',
        encoding: 'utf-8',
        total_chars: 9000,
        count: 2,
        returned: 2,
        truncated: false,
        limit: 5000,
        message: '',
        chapters: [
          { index: 1, title: '第一章 雪', offset: 0, chars: 5000 },
          { index: 2, title: '第二章 火', offset: 5000, chars: 4000 }
        ],
        ...over
      }
    })

    /** 宿主 novels/read 的**一段**（引用要的就是一段）：位置与长度照参数回。 */
    const sliceAt = (offset: number, chars: number, text?: string): unknown => ({
      ok: true,
      result: {
        name: '长夜.txt',
        offset,
        chars,
        requested_chars: chars,
        total_chars: 9000,
        at_end: offset + chars >= 9000,
        bytes: 2048,
        mtime: 1758900000,
        encoding: 'utf-8',
        text: text === undefined ? '原文' + offset + '-' + chars : text
      }
    })

    /** 把 novels/read 接成"照参数回一段"：正文那种整页读法也走它。 */
    const readsOnDemand =
      (text?: string): RequestStub =>
      (_method: string, params: unknown) => {
        const asked = (params ?? {}) as { offset?: number; chars?: number }
        return sliceAt(asked.offset ?? 0, asked.chars ?? 0, text)
      }

    /** 宿主 novels/read 的一页：把 offset 写进正文，好在断言里认出跳到了哪儿。 */
    const readAt = (offset: number): unknown => ({
      ok: true,
      result: {
        name: '长夜.txt',
        offset,
        chars: 4000,
        requested_chars: 4000,
        total_chars: 9000,
        at_end: offset >= 5000,
        bytes: 2048,
        mtime: 1758900000,
        encoding: 'utf-8',
        text: '第 ' + offset + ' 字'
      }
    })

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
      expect(novelLine('长夜.txt')?.getAttribute('data-open'), '在读的那一行要看得出来').toBe(
        'true'
      )

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
                    message:
                      '原文目录里已经有 长夜.txt 了（2048 字节）：要换成你这份就带 overwrite 再来一次'
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

    it('closes the import popup by the backdrop, Esc and 取消, and on a successful import', async () => {
      installBridge({
        request: host({
          'novels/list': listing([]),
          'novels/import': {
            ok: true,
            result: { imported: true, name: '长夜.txt', bytes: 2048, created_dir: false }
          }
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openNovels()

      const popup = (): HTMLElement => view(NOVEL_FORM_ID)
      expect(popup().dataset.open, '平时是收着的（它就压在页面上面，不该常驻）').toBe('0')

      button(NOVEL_VIEW_ID, '导入…')?.click()
      expect(popup().dataset.open).toBe('1')

      // 暗底就是弹窗那一层自己：点它（事件落在它身上）＝退出，不该只能去够那颗「取消」。
      popup().dispatchEvent(new MouseEvent('click', { bubbles: true }))
      expect(popup().dataset.open).toBe('0')

      button(NOVEL_VIEW_ID, '导入…')?.click()
      // Esc 从光标所在的那一格冒上来（打开时光标就在路径上，见 toggleNovelForm）。
      pathInput().dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
      expect(popup().dataset.open).toBe('0')

      button(NOVEL_VIEW_ID, '导入…')?.click()
      button(NOVEL_FORM_ID, '取消')?.click()
      expect(popup().dataset.open, '取消只管关，不接进来').toBe('0')

      // 接进来了就把弹窗收掉：结果在页顶那条与列表里，卡片继续举着只会挡住刚更新出来的那一列。
      button(NOVEL_VIEW_ID, '导入…')?.click()
      pathInput().value = 'D:/books/长夜.txt'
      button(NOVEL_FORM_ID, '导入')?.click()
      await flush()
      expect(popup().dataset.open).toBe('0')
      expect(hintLine().textContent).toContain('接进来了 长夜.txt')
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
      expect(view(NOVEL_READER_ID).textContent, '正文被换掉了，旧的字不能还挂在屏幕上').toBe(
        '选中上面一篇，正文显示在这里。'
      )
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
      expect(
        novelCalls(bridge, 'novels/list'),
        '删完要重新列，别让人对着已经不存在的名字点'
      ).toHaveLength(2)
    })

    it('hands a novel to the conversation without sending it for the user', async () => {
      const bridge = installBridge({ request: host({ 'novels/list': listing([novelRow()]) }) })
      setupDom()
      new Function(script)()
      await openPanel()
      await openNovels()

      lineButton('长夜.txt', '发到对话')?.click()

      expect(view(CHAT_VIEW_ID).style.display).toBe('flex')
      expect(view(NOVEL_VIEW_ID).style.display).toBe('none')
      const input = document.getElementById(INPUT_ID) as HTMLTextAreaElement
      expect(input.value).toBe('用原文「长夜.txt」开工')
      expect(novelCalls(bridge, 'agent/chat'), '发不发由用户自己按').toHaveLength(0)
    })

    it('cuts the novel into chapters and jumps to the chapter that was clicked', async () => {
      const bridge = installBridge({
        request: host({
          'novels/list': listing([novelRow()]),
          'novels/chapters': chapterList(),
          'novels/read': (_method: string, params: unknown) =>
            readAt((params as { offset: number }).offset)
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openNovels()

      expect(view(NOVEL_SIDE_ID).dataset.open, '还没打开哪一篇，左栏没有意义').toBe('0')

      lineButton('长夜.txt', '读')?.click()
      await flush()

      expect(bridge.request).toHaveBeenCalledWith('novels/chapters', { name: '长夜.txt' })
      expect(view(NOVEL_SIDE_ID).dataset.open).toBe('1')
      expect(sideTitles()).toEqual(['第一章 雪', '第二章 火'])
      expect(sideRow(0).dataset.current, '正读的是第一章').toBe('true')
      expect(sideRow(1).dataset.current).toBeUndefined()

      // 点第二章：位置由宿主给（章里那个 offset），面板一个数都不自己算。
      sideRow(1).click()
      await flush()

      expect(bridge.request).toHaveBeenCalledWith('novels/read', {
        name: '长夜.txt',
        offset: 5000
      })
      expect(view(NOVEL_READER_ID).textContent).toBe('第 5000 字')
      expect(sideRow(1).dataset.current).toBe('true')
      expect(sideRow(0).dataset.current, '标记是挪过去，不是又多一个').toBeUndefined()

      // 翻页也要把标记挪回去：不然读完第二章，目录里还指着第二章。
      button(NOVEL_PAGER_ID, '上一页')?.click()
      await flush()

      expect(view(NOVEL_READER_ID).textContent).toBe('第 1000 字')
      expect(sideRow(0).dataset.current).toBe('true')
      expect(sideRow(1).dataset.current).toBeUndefined()
    })

    it('finds a phrase in the open novel and jumps to a hit', async () => {
      const bridge = installBridge({
        request: host({
          'novels/list': listing([novelRow()]),
          'novels/chapters': chapterList(),
          'novels/search': (_method: string, params: unknown) => ({
            ok: true,
            result: {
              name: '长夜.txt',
              query: (params as { query: string }).query,
              matched: 1,
              truncated: false,
              limit: 100,
              matches: [{ offset: 4321, snippet: '…他想起那一夜…' }]
            }
          }),
          'novels/read': (_method: string, params: unknown) =>
            readAt((params as { offset: number }).offset)
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openNovels()

      lineButton('长夜.txt', '读')?.click()
      await flush()

      const input = document.getElementById(NOVEL_SEARCH_ID) as HTMLInputElement
      input.value = ' 那一夜 '
      button(NOVEL_SIDE_ID, '找')?.click()
      await flush()

      // 原样搜，连首尾空格都不动：宿主那边只看字面（novels.py），面板"顺手" trim 一下
      // 就会给出一个用户没要的位置。
      expect(bridge.request).toHaveBeenCalledWith('novels/search', {
        name: '长夜.txt',
        query: ' 那一夜 '
      })
      expect(sideRows()).toHaveLength(1)
      expect(sideRow(0).textContent, '片段是宿主给的，面板不自己裁正文').toBe('…他想起那一夜…')
      expect(view(NOVEL_SIDE_ID).querySelector('.cs-novel-side-title')?.textContent).toContain(
        '1 处'
      )
      expect(
        document.getElementById(NOVEL_TOC_BACK_ID)?.style.display,
        '搜索结果这一屏才有「返回目录」'
      ).not.toBe('none')

      sideRow(0).click()
      await flush()

      expect(bridge.request).toHaveBeenCalledWith('novels/read', {
        name: '长夜.txt',
        offset: 4321
      })
      expect(view(NOVEL_READER_ID).textContent).toBe('第 4321 字')

      document.getElementById(NOVEL_TOC_BACK_ID)?.click()
      await flush()

      expect(sideTitles()).toEqual(['第一章 雪', '第二章 火'])
      expect(document.getElementById(NOVEL_TOC_BACK_ID)?.style.display).toBe('none')
    })

    it('keeps an empty search local instead of asking the host for nothing', async () => {
      const bridge = installBridge({
        request: host({ 'novels/list': listing([novelRow()]), 'novels/chapters': chapterList() })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openNovels()

      lineButton('长夜.txt', '读')?.click()
      await flush()

      const input = document.getElementById(NOVEL_SEARCH_ID) as HTMLInputElement
      input.value = '   '
      button(NOVEL_SIDE_ID, '找')?.click()
      await flush()

      expect(novelCalls(bridge, 'novels/search'), '搜空白宿主也会报错，别白跑一趟').toHaveLength(0)
      expect(hintLine().textContent).toContain('不能是空的')
      expect(hintLine().getAttribute('data-tone')).toBe('error')
      // 还没开始找，目录照旧摆在那儿。
      expect(sideTitles()).toEqual(['第一章 雪', '第二章 火'])
    })

    it('hides the side column on request, and does not re-cut what it already has', async () => {
      const bridge = installBridge({
        request: host({
          'novels/list': listing([novelRow()]),
          'novels/chapters': chapterList(),
          'novels/read': (_method: string, params: unknown) =>
            readAt((params as { offset: number }).offset)
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openNovels()

      lineButton('长夜.txt', '读')?.click()
      await flush()

      const toc = document.getElementById(NOVEL_TOC_ID) as HTMLButtonElement
      toc.click()
      expect(view(NOVEL_SIDE_ID).dataset.open, '收起来给正文让地方').toBe('0')
      expect(toc.dataset.active).toBe('false')

      toc.click()
      await flush()

      expect(view(NOVEL_SIDE_ID).dataset.open).toBe('1')
      expect(toc.dataset.active).toBe('true')
      // 切目录得把整篇扫一遍：同一篇关掉再开是同一个答案，不该再问一遍宿主。
      expect(novelCalls(bridge, 'novels/chapters')).toHaveLength(1)
    })

    it('re-cuts the tree for whichever novel is open now', async () => {
      const chaptersOf = (name: string): unknown => ({
        ok: true,
        result: {
          name,
          encoding: 'utf-8',
          total_chars: 100,
          count: 1,
          returned: 1,
          truncated: false,
          limit: 5000,
          message: '',
          chapters: [{ index: 1, title: name + ' 的第一章', offset: 0, chars: 100 }]
        }
      })
      installBridge({
        request: host({
          'novels/list': listing([novelRow(), novelRow({ name: '另一本.md', bytes: 1024 })]),
          'novels/chapters': (_method: string, params: unknown) =>
            chaptersOf((params as { name: string }).name),
          'novels/read': (_method: string, params: unknown) =>
            readAt((params as { offset: number }).offset)
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openNovels()

      lineButton('长夜.txt', '读')?.click()
      await flush()
      expect(sideTitles()).toEqual(['长夜.txt 的第一章'])

      // 换一篇：左栏必须跟着换。留着上一本那棵树，点下去跳的是别的书里的位置。
      lineButton('另一本.md', '读')?.click()
      await flush()

      expect(sideTitles()).toEqual(['另一本.md 的第一章'])
    })

    it('says in the side column why a novel has no chapters', async () => {
      installBridge({
        request: host({
          'novels/list': listing([novelRow()]),
          'novels/chapters': chapterList({
            count: 1,
            returned: 1,
            message: '这篇没切出章节（整行标题一条也没认出来）：按页码翻，或搜一串字跳过去',
            chapters: [{ index: 1, title: '全文', offset: 0, chars: 9000 }]
          }),
          'novels/read': (_method: string, params: unknown) =>
            readAt((params as { offset: number }).offset)
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openNovels()

      lineButton('长夜.txt', '读')?.click()
      await flush()

      expect(sideList().textContent).toContain('没切出章节')
      // 但路没断：还留着「全文」一条，照样翻得下去。
      expect(sideTitles()).toEqual(['全文'])
    })

    it('writes the host reason into the side column when it cannot cut chapters', async () => {
      installBridge({
        request: host({
          'novels/list': listing([novelRow()]),
          'novels/chapters': {
            ok: false,
            error: { code: -32603, message: '长夜.txt 认不出编码：试过 utf-8 与 gb18030 都不成' }
          },
          'novels/read': (_method: string, params: unknown) =>
            readAt((params as { offset: number }).offset)
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openNovels()

      lineButton('长夜.txt', '读')?.click()
      await flush()

      // 眼睛就在那一栏上，而失败之后它是空的：空着不说为什么，等于让人再点一遍。
      expect(sideList().textContent).toContain('切不出目录')
      expect(sideList().textContent).toContain('认不出编码')
      expect(view(NOVEL_READER_ID).textContent, '目录切不出来不代表正文读不了').toBe('第 0 字')
    })

    it('quotes the page it is reading and sends it as a block in front of the words', async () => {
      const bridge = installBridge({
        request: host({
          'novels/list': listing([novelRow()]),
          'novels/chapters': chapterList(),
          'novels/read': readsOnDemand()
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openNovels()

      lineButton('长夜.txt', '读')?.click()
      await flush()

      button(NOVEL_PAGER_ID, '引用')?.click()
      await flush()

      // 要多少字由面板说，回多少字由宿主说：面板一个数都不自己算（位置、字数都认宿主的）。
      const asked = novelCalls(bridge, 'novels/read')
      expect(asked[asked.length - 1]).toEqual([
        'novels/read',
        { name: '长夜.txt', offset: 0, chars: 800 }
      ])
      expect(view(CHAT_VIEW_ID).style.display, '卡片在对话页那一边，切过去才看得见').toBe('flex')
      expect(view(NOVEL_VIEW_ID).style.display).toBe('none')
      const card = view(QUOTE_BAR_ID).querySelector('.cs-quote')
      expect(card?.querySelector('.cs-quote-title')?.textContent).toBe(
        '引用 长夜.txt · 第 0 字起 800 字'
      )
      expect(card?.querySelector('.cs-quote-drop'), '还没发出去，能去掉').not.toBeNull()
      expect(document.getElementById(STATUS_ID)?.textContent).toContain('可以去掉')

      await send('照这个写')

      // 发出去的是"引用块 + 空一行 + 用户自己的话"：块里带位置，模型要自己去翻全文时有入口。
      expect(bridge.request).toHaveBeenCalledWith('agent/chat', {
        text: '[引用 长夜.txt 0 800]\n原文0-800\n[/引用]\n\n照这个写',
        session_id: 'default',
        // 他这会儿正开着 长夜.txt 在读，这一轮就把它一起带上：引用块里写的文件名是"这一条
        // 引用"，而面板上开着哪一篇是另一件事（见 chatContext）。
        context: { novel: '长夜.txt' }
      })
      expect(view(QUOTE_BAR_ID).style.display, '发出去了，卡就不再挂着').toBe('none')
      const bubble = rows('user')[0]
      expect(bubble?.querySelector('.cs-quote')).not.toBeNull()
      expect(bubble?.querySelector('.cs-user-words')?.textContent).toBe('照这个写')
      expect(bubble?.querySelector('.cs-quote-drop'), '发出去的那张没有 ×').toBeNull()
    })

    it('quotes the passage selected in the reader instead of the whole page', async () => {
      const bridge = installBridge({
        request: host({
          'novels/list': listing([novelRow()]),
          'novels/chapters': chapterList(),
          // 正文得够长，好在里面真的取一段选区（一页的文本节点就是它）。
          'novels/read': readsOnDemand('一二三四五六七八九十甲乙丙丁戊己')
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openNovels()

      lineButton('长夜.txt', '读')?.click()
      await flush()

      const reader = view(NOVEL_READER_ID)
      const range = document.createRange()
      range.setStart(reader.firstChild as Node, 4)
      range.setEnd(reader.firstChild as Node, 9)
      const selection = window.getSelection()
      selection?.removeAllRanges()
      selection?.addRange(range)

      button(NOVEL_PAGER_ID, '引用')?.click()
      await flush()

      // 页起点 0 + 节点内偏移 4，一共 5 个字 —— 这就是"选中的那段在原文里的位置"。
      const asked = novelCalls(bridge, 'novels/read')
      expect(asked[asked.length - 1]).toEqual([
        'novels/read',
        { name: '长夜.txt', offset: 4, chars: 5 }
      ])
      const card = view(QUOTE_BAR_ID).querySelector('.cs-quote')
      expect(card?.querySelector('.cs-quote-title')?.textContent).toBe(
        '引用 长夜.txt · 第 4 字起 5 字'
      )
      expect(document.getElementById(STATUS_ID)?.textContent).toContain('引用了选中的 5 字')
    })

    it('drops a card that is not wanted any more', async () => {
      const bridge = installBridge({
        request: host({
          'novels/list': listing([novelRow()]),
          'novels/chapters': chapterList(),
          'novels/read': readsOnDemand()
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openNovels()

      lineButton('长夜.txt', '读')?.click()
      await flush()
      button(NOVEL_PAGER_ID, '引用')?.click()
      await flush()

      expect(view(QUOTE_BAR_ID).querySelectorAll('.cs-quote')).toHaveLength(1)

      view(QUOTE_BAR_ID).querySelector<HTMLElement>('.cs-quote-drop')?.click()

      expect(view(QUOTE_BAR_ID).style.display, '一张都没有了就整栏收掉').toBe('none')

      await send('就这些，不加原文了')

      expect(bridge.request).toHaveBeenCalledWith('agent/chat', {
        text: '就这些，不加原文了',
        session_id: 'default',
        // 引用卡丢光了，可面板上那篇原文还开着：这句话里的"原文"只剩这一个落点。
        context: { novel: '长夜.txt' }
      })
    })

    it('stops at four quotes instead of piling them up', async () => {
      const bridge = installBridge({
        request: host({
          'novels/list': listing([novelRow()]),
          'novels/chapters': chapterList(),
          'novels/read': readsOnDemand()
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openNovels()

      lineButton('长夜.txt', '读')?.click()
      await flush()

      for (let index = 0; index < 4; index += 1) {
        await openNovels() // 引用完会切到对话页去，得回到小说页再点下一次
        button(NOVEL_PAGER_ID, '引用')?.click()
        await flush()
      }
      expect(view(QUOTE_BAR_ID).querySelectorAll('.cs-quote')).toHaveLength(4)

      const asked = novelCalls(bridge, 'novels/read').length
      await openNovels()
      button(NOVEL_PAGER_ID, '引用')?.click()
      await flush()

      // 第五张不给，而且要说明白为什么 —— 静默丢掉一张，用户会以为带上了。
      expect(novelCalls(bridge, 'novels/read'), '超了就不去问宿主了').toHaveLength(asked)
      expect(view(QUOTE_BAR_ID).querySelectorAll('.cs-quote')).toHaveLength(4)
      expect(hintLine().textContent).toContain('最多带 4 段引用')
    })

    it('refuses to make a card out of an empty passage', async () => {
      installBridge({
        request: host({
          'novels/list': listing([novelRow()]),
          'novels/chapters': chapterList(),
          'novels/read': (_method: string, params: unknown) => {
            const asked = (params ?? {}) as { offset?: number; chars?: number }
            // 翻页那次有正文；要 800 字的那一次（引用）宿主说"这儿只剩空白"。
            return asked.chars === 800
              ? sliceAt(asked.offset ?? 0, 0, ' ')
              : sliceAt(asked.offset ?? 0, 4000, '正文')
          }
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openNovels()

      lineButton('长夜.txt', '读')?.click()
      await flush()
      button(NOVEL_PAGER_ID, '引用')?.click()
      await flush()

      // 空白一段做成的卡发出去就是"这里本来有段原文"：谁都不知道它是空的。
      expect(view(QUOTE_BAR_ID).querySelectorAll('.cs-quote')).toHaveLength(0)
      expect(view(QUOTE_BAR_ID).style.display).toBe('none')
      expect(hintLine().textContent).toContain('只有空白')
      expect(view(NOVEL_VIEW_ID).style.display, '没成就不切页，让用户接着在这儿改').toBe('flex')
    })

    it('paints a quote back as a card when the panel is reopened', async () => {
      // 存档里就是发出去的那段文本：面板照同一套语法把它拆回卡片（同一份文本，两处画法一致）。
      const sent = '[引用 长夜.txt 1200 40]\n那一刻他才知道什么叫冷\n[/引用]\n\n照这个写'
      installBridge({
        request: (method: string): unknown =>
          method === 'agent/history'
            ? { ok: true, result: { entries: [{ type: 'user', text: sent }] } }
            : { ok: true, result: { text: '答案在此' } }
      })
      setupDom()
      new Function(script)()
      await openPanel()

      const bubble = rows('user')[0]
      expect(
        bubble?.querySelector('.cs-quote-title')?.textContent,
        '位置与字数照引用块里那份念，不去猜'
      ).toBe('引用 长夜.txt · 第 1200 字起 40 字')
      expect(bubble?.querySelector('.cs-quote-body')?.textContent).toBe('那一刻他才知道什么叫冷')
      expect(bubble?.querySelector('.cs-user-words')?.textContent).toBe('照这个写')
    })

    it('leaves a message that only looks like a quote alone', async () => {
      // 少一行收尾：形状不完整，整条照普通话画（宁可少画一张卡，也不猜到哪里为止）。
      const odd = '[引用 长夜.txt 1200 40]\n那一刻他才知道什么叫冷'
      installBridge({
        request: (method: string): unknown =>
          method === 'agent/history'
            ? { ok: true, result: { entries: [{ type: 'user', text: odd }] } }
            : { ok: true, result: { text: '答案在此' } }
      })
      setupDom()
      new Function(script)()
      await openPanel()

      const bubble = rows('user')[0]
      expect(bubble?.querySelector('.cs-quote')).toBeNull()
      expect(saidOf(bubble)).toBe(odd)
    })

    describe('批量删几篇', () => {
      it('deletes several novels at once, asking a second time first', async () => {
        const bridge = installBridge({
          request: host({
            'novels/list': listing([novelRow(), novelRow({ name: '另一本.md' })]),
            'novels/delete': (_method: string, params: unknown) => ({
              ok: true,
              result: { name: (params as { name: string }).name }
            })
          })
        })
        setupDom()
        new Function(script)()
        await openPanel()
        await openNovels()

        const pick = (name: string): HTMLInputElement =>
          novelLine(name)?.querySelector('.cs-novel-pick') as HTMLInputElement
        const batchText = (): string =>
          view(NOVEL_BATCH_ID).querySelector('.cs-novel-batch-count')?.textContent ?? ''
        const pickOn = async (name: string): Promise<void> => {
          const box = pick(name)
          box.checked = true
          box.dispatchEvent(new Event('change'))
          await flush()
        }

        expect(batchText(), '没勾之前先说清这一栏是干什么的').toContain('没勾选')

        await pickOn('长夜.txt')
        await pickOn('另一本.md')

        expect(batchText()).toBe('选中 2 篇：长夜.txt、另一本.md')
        expect(novelLine('长夜.txt')?.getAttribute('data-picked')).toBe('true')

        document.getElementById(NOVEL_BATCH_DELETE_ID)?.click()

        expect(novelCalls(bridge, 'novels/delete'), '第一下只是问一次').toHaveLength(0)
        expect(document.getElementById(NOVEL_BATCH_DELETE_ID)?.textContent).toBe('确认删除 2 篇')

        document.getElementById(NOVEL_BATCH_DELETE_ID)?.click()
        await flush()

        // 宿主一次只删一篇（novels/delete 接一个名字），所以面板串着一篇一篇来。
        expect(novelCalls(bridge, 'novels/delete').map((call) => call[1])).toEqual([
          { name: '长夜.txt' },
          { name: '另一本.md' }
        ])
        expect(hintLine().textContent).toContain('删了 2 篇：长夜.txt、另一本.md')
        expect(batchText(), '删完把勾清掉').toContain('没勾选')
      })

      it('reports which of the picked novels did not get deleted', async () => {
        installBridge({
          request: host({
            'novels/list': listing([novelRow(), novelRow({ name: '另一本.md' })]),
            'novels/delete': (_method: string, params: unknown) =>
              (params as { name: string }).name === '长夜.txt'
                ? { ok: true, result: {} }
                : { ok: false, error: { message: '被别的程序占着' } }
          })
        })
        setupDom()
        new Function(script)()
        await openPanel()
        await openNovels()

        const pickOn = (name: string): void => {
          const box = novelLine(name)?.querySelector('.cs-novel-pick') as HTMLInputElement
          box.checked = true
          box.dispatchEvent(new Event('change'))
        }
        pickOn('长夜.txt')
        pickOn('另一本.md')

        document.getElementById(NOVEL_BATCH_DELETE_ID)?.click()
        document.getElementById(NOVEL_BATCH_DELETE_ID)?.click()
        await flush()

        // 一篇删不动不该把后面几篇卡住，也不能假装这一批都删掉了。
        expect(hintLine().textContent).toContain('删了 1 篇：长夜.txt')
        expect(hintLine().textContent).toContain('没删成 1 篇：另一本.md（被别的程序占着）')
        expect(hintLine().getAttribute('data-tone')).toBe('error')
      })

      it('selects the whole list at once, and clears it without touching the disk', async () => {
        const bridge = installBridge({
          request: host({ 'novels/list': listing([novelRow(), novelRow({ name: '另一本.md' })]) })
        })
        setupDom()
        new Function(script)()
        await openPanel()
        await openNovels()

        const batchText = (): string =>
          view(NOVEL_BATCH_ID).querySelector('.cs-novel-batch-count')?.textContent ?? ''
        const pick = (name: string): HTMLInputElement =>
          novelLine(name)?.querySelector('.cs-novel-pick') as HTMLInputElement

        document.getElementById(NOVEL_BATCH_ALL_ID)?.click()
        await flush()

        expect(batchText()).toBe('选中 2 篇：长夜.txt、另一本.md')
        expect(pick('长夜.txt').checked, '全选要把每一行的方框也真的勾上').toBe(true)

        document.getElementById(NOVEL_BATCH_NONE_ID)?.click()
        await flush()

        expect(batchText()).toContain('没勾选')
        expect(pick('长夜.txt').checked).toBe(false)
        expect(novelCalls(bridge, 'novels/delete'), '勾选与清空都不动磁盘').toHaveLength(0)
      })
    })

    describe('章节目录与立项', () => {
      const sideTitle = (): string =>
        document.querySelector(`#${NOVEL_SIDE_ID} .cs-novel-side-title`)?.textContent ?? ''

      it('draws each chapter as its share of the whole novel, and says where I am', async () => {
        installBridge({
          request: host({
            'novels/list': listing([novelRow()]),
            'novels/chapters': chapterList(),
            'novels/read': (_method: string, params: unknown) =>
              readAt((params as { offset: number }).offset)
          })
        })
        setupDom()
        new Function(script)()
        await openPanel()
        await openNovels()

        lineButton('长夜.txt', '读')?.click()
        await flush()

        expect(sideTitle()).toContain('2 章')
        expect(sideTitle()).toContain('9000 字')
        expect(sideTitle()).toContain('读到第 1 章')

        // 字数与那条占比用的是同一对数（chapter.chars / meta.total_chars）：面板不另外量正文。
        expect(sideRow(0).querySelector('.cs-novel-side-meta')?.textContent).toBe('5000 字 · 56%')
        expect(sideRow(0).querySelector<HTMLElement>('.cs-novel-side-bar-fill')?.style.width).toBe(
          '55.56%'
        )
        expect(sideRow(1).querySelector('.cs-novel-side-meta')?.textContent).toBe('4000 字 · 44%')

        sideRow(1).click()
        await flush()

        expect(sideRow(1).dataset.current).toBe('true')
        expect(sideTitle(), '跳章之后那一行也得跟着走').toContain('读到第 2 章')
      })

      it('opens the new-project form with this novel picked as the source', async () => {
        const bridge = installBridge({ request: host({ 'novels/list': listing([novelRow()]) }) })
        setupDom()
        new Function(script)()
        await openPanel()
        await openNovels()

        lineButton('长夜.txt', '以此立项')?.click()
        await flush()

        expect(view(NOVEL_VIEW_ID).style.display).toBe('none')
        expect(view(PROJECT_VIEW_ID).style.display).toBe('flex')
        expect(view(PROJECT_FORM_ID).getAttribute('data-open')).toBe('1')
        expect(
          (document.getElementById(PROJECT_FORM_NAME_ID) as HTMLInputElement).value,
          '剧名就是目录名，别带着 .txt'
        ).toBe('长夜')
        expect((document.getElementById(PROJECT_FORM_NOVEL_ID) as HTMLSelectElement).value).toBe(
          '长夜.txt'
        )
        expect(view(PROJECT_HINT_ID).textContent).toContain('拿「长夜.txt」当原著')
        expect(novelCalls(bridge, 'projects/create'), '建不建、建几集是人自己定').toHaveLength(0)
      })
    })
  })

  describe('一键跑 skill', () => {
    /**
     * skill 目录是引擎报上来的（宿主原样转，见 lib/comfy_studio/skills/catalog.py）：
     * 面板照念，参数一个都不自己编。
     */
    const skillRow = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
      id: 'text-to-image',
      title: '文生图',
      description: '一句提示词出一张图',
      tags: ['示例'],
      params: [
        {
          name: 'ckpt_name',
          type: 'string',
          required: true,
          description: '底模',
          default: 'sd_xl.safetensors',
          hasDefault: true
        },
        {
          name: 'prompt',
          type: 'string',
          required: true,
          description: '提示词',
          default: '一间亮着灯的旧书店',
          hasDefault: true
        }
      ],
      ...over
    })

    const catalog = (skills: unknown[]): unknown => ({ ok: true, result: { skills } })

    /** 引擎一次输出的图（见引擎侧 skills/types.py 的 SkillRunResult.to_json）。 */
    const image = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
      node: '9',
      filename: 'comfy-studio_00001_.png',
      subfolder: '',
      type: 'output',
      url: 'http://127.0.0.1:8188/view?filename=comfy-studio_00001_.png&type=output',
      ...over
    })

    const runResult = (over: Record<string, unknown> = {}): unknown => ({
      ok: true,
      result: {
        skill_id: 'text-to-image',
        isError: false,
        text: '跑完了',
        data: { prompt_id: 'p-1', images: [image()] },
        ...over
      }
    })

    /** 只有 skills/* 那两件事走自己的桩；开抽屉要问的那些保持默认。 */
    const host =
      (handlers: Record<string, unknown>): RequestStub =>
      (method, params) =>
        method in handlers
          ? typeof handlers[method] === 'function'
            ? (handlers[method] as RequestStub)(method, params)
            : handlers[method]
          : { ok: true, result: { text: '答案在此' } }

    const skillSelect = (): HTMLSelectElement =>
      document.getElementById(SKILL_ID) as HTMLSelectElement
    const runButton = (): HTMLButtonElement =>
      document.getElementById(SKILL_RUN_ID) as HTMLButtonElement
    const card = (): Element | null => rows('skill')[0] ?? null
    const runCalls = (bridge: StudioBridge): unknown[][] =>
      bridge.request.mock.calls.filter((call: unknown[]) => call[0] === 'skills/run')

    /** 开面板 + 跑一遍，返回桥与那张卡（用例里几乎每个都要这三步）。 */
    const runOnce = async (
      handlers: Record<string, unknown> = {}
    ): Promise<{ bridge: StudioBridge; card: Element | null }> => {
      const bridge = installBridge({
        // 默认这一趟跑成、出来一张图；要别的结果（失败、没图）的用例自己覆盖。
        request: host({ 'skills/run': runResult(), ...handlers })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      document.getElementById(SKILL_RUN_ID)?.click()
      await flush()
      return { bridge, card: card() }
    }

    it('runs the chosen skill with the defaults the skill itself declares', async () => {
      const bridge = installBridge({
        request: host({ 'skills/list': catalog([skillRow()]), 'skills/run': runResult() })
      })
      setupDom()
      new Function(script)()
      await openPanel()

      expect(skillSelect().value).toBe('text-to-image')
      document.getElementById(SKILL_RUN_ID)?.click()
      await flush()

      // 参数原样来自 skill 文件里的 default：面板不替它写值（写错的值不会报错，只会跑出另一套图）。
      expect(runCalls(bridge)).toEqual([
        [
          'skills/run',
          {
            skill_id: 'text-to-image',
            params: { ckpt_name: 'sd_xl.safetensors', prompt: '一间亮着灯的旧书店' }
          }
        ]
      ])
      expect(document.getElementById(STATUS_ID)?.textContent).toContain('1 张图')
    })

    it('refuses to run when a required parameter has no default', async () => {
      const bridge = installBridge({
        request: host({
          'skills/list': catalog([
            skillRow({
              params: [
                {
                  name: 'ckpt_name',
                  type: 'string',
                  required: true,
                  default: null,
                  hasDefault: false
                },
                {
                  name: 'prompt',
                  type: 'string',
                  required: true,
                  default: '一间亮着灯的旧书店',
                  hasDefault: true
                }
              ]
            })
          ])
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()

      document.getElementById(SKILL_RUN_ID)?.click()
      await flush()

      // 必填没默认值就不跑，而且要点名是哪个参数 —— 编一个值塞进去，出来的图是错的还不报错。
      expect(runCalls(bridge)).toHaveLength(0)
      expect(card()).toBeNull()
      expect(document.getElementById(STATUS_ID)?.textContent).toContain('ckpt_name')
      expect(document.getElementById(STATUS_ID)?.textContent).toContain('没有默认值')
    })

    it('paints the images the engine reports, address and all', async () => {
      const { card: row } = await runOnce({ 'skills/list': catalog([skillRow()]) })

      const img = row?.querySelector('img.cs-skill-image')
      expect(img?.getAttribute('src'), '地址照引擎给的用，面板不自己拼 /view').toBe(
        'http://127.0.0.1:8188/view?filename=comfy-studio_00001_.png&type=output'
      )
      expect(row?.querySelector('.cs-skill-caption')?.textContent).toBe('comfy-studio_00001_.png')
      expect(row?.querySelector('.cs-skill-state')?.textContent).toBe('完成 · 1 张图')
    })

    it('says so when the engine ran but produced no image', async () => {
      const { card: row } = await runOnce({
        'skills/list': catalog([skillRow()]),
        'skills/run': runResult({
          text: '{"prompt_id":"p-1","images":[]}',
          data: { prompt_id: 'p-1', images: [] }
        })
      })

      // 一张图都没有时不能画成一片空白：那看着像"还在跑"。
      expect(row?.querySelector('.cs-skill-image')).toBeNull()
      expect(row?.querySelector('.cs-skill-state')?.textContent).toBe('完成（没有图片输出）')
      expect(row?.textContent).toContain('{"prompt_id":"p-1","images":[]}')
      expect(document.getElementById(STATUS_ID)?.textContent).toContain('没报出图片输出')
    })

    it('keeps the engine words when the run itself failed', async () => {
      const { card: row } = await runOnce({
        'skills/list': catalog([skillRow()]),
        'skills/run': runResult({ isError: true, text: '显存不够', data: null })
      })

      expect(row?.getAttribute('data-state')).toBe('error')
      expect(row?.querySelector('.cs-skill-state')?.textContent).toBe('失败')
      expect(row?.textContent).toContain('显存不够')
      expect(document.getElementById(STATUS_ID)?.textContent).toContain('失败')
    })

    it('turns an image that will not load into a line that says why', async () => {
      const { card: row } = await runOnce({ 'skills/list': catalog([skillRow()]) })

      const img = row?.querySelector('img.cs-skill-image')
      img?.dispatchEvent(new Event('error'))
      await flush()

      // 留一个空框会被当成"图还在路上"：换成一行字，并把地址写上，用户能自己去查。
      expect(row?.querySelector('img.cs-skill-image')).toBeNull()
      expect(row?.querySelector('.cs-skill-image-note')?.textContent).toContain(
        'http://127.0.0.1:8188/view?filename=comfy-studio_00001_.png&type=output'
      )
    })

    it('runs one at a time instead of stacking them up', async () => {
      const bridge = installBridge({
        request: host({
          'skills/list': catalog([skillRow()]),
          // 第一遍一直不回来：这时候界面上的状态就是"正在跑"。
          'skills/run': () => new Promise(() => {})
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()

      document.getElementById(SKILL_RUN_ID)?.click()
      await flush()
      // 跑着的时候按钮还按得动（灭掉的按钮不会解释自己为什么灭），但选择先灭掉：跑着改选择没意义。
      expect(runButton().disabled).toBe(false)
      expect(skillSelect().disabled).toBe(true)

      document.getElementById(SKILL_RUN_ID)?.click()
      await flush()

      // 引擎跑一套工作流占着显存，叠着按只会两边都慢 —— 按了要说话，不能装作没看见。
      expect(runCalls(bridge)).toHaveLength(1)
      expect(document.getElementById(STATUS_ID)?.textContent).toContain('还在跑')
    })

    it('explains a dead row instead of leaving it empty', async () => {
      installBridge({ request: host({ 'skills/list': catalog([]) }) })
      setupDom()
      new Function(script)()
      await openPanel()

      // 引擎没起来（skill 目录在引擎侧）时，空下拉看起来像面板坏了。
      expect(skillSelect().options[0]?.textContent).toBe('（引擎没报出 skill）')
      expect(runButton().disabled).toBe(true)
    })

    it('keeps the choice when the catalog is refreshed', async () => {
      installBridge({
        request: host({
          'skills/list': catalog([
            skillRow(),
            skillRow({ id: 'text-to-video', title: '文生视频', params: [] })
          ])
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()

      // 真选一下（下拉的选中只靠 change 事件回到面板那里，直接改 value 用户按不出来）。
      skillSelect().value = 'text-to-video'
      skillSelect().dispatchEvent(new Event('change'))

      // 每轮对话结束都会重读一遍目录（用户可能刚往 skills 目录里加了一套）：刷新一次就跳回
      // 第一个，等于替用户改了选择。
      await send('你刚说的那个再跑一遍')

      expect(skillSelect().value).toBe('text-to-video')
    })
  })

  describe('一键跑渲染目标', () => {
    /**
     * 宿主 renders/list 里的一条目标（形状见 lib/comfy_studio/renders/catalog.py 的 to_json）：
     * params 用的是与 skill 同一套字段（name/type/required/default/hasDefault/description），
     * referenceImages 说明这只目标收不收参考图（视频那几只收）。
     */
    const target = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
      id: 'character-board',
      title: '角色定妆板',
      description: '给一个角色出定妆板',
      file: '01_角色定妆板_Qwen2512.json',
      fileExists: true,
      tags: ['image'],
      referenceImages: false,
      params: [
        {
          name: 'prompt',
          type: 'string',
          required: true,
          default: null,
          hasDefault: false,
          description: '这个角色长什么样'
        }
      ],
      ...over
    })

    const listing = (targets: unknown[], over: Record<string, unknown> = {}): unknown => ({
      ok: true,
      result: {
        workflows_dir: 'D:/comfy/user/default/workflows/AIGC中国风漫剧',
        note: null,
        targets,
        ...over
      }
    })

    /** 跑完一次的引擎回包，形状与 skill 那次同一份（多 notes / saved 两样）。 */
    const runResult = (over: Record<string, unknown> = {}): unknown => ({
      ok: true,
      result: {
        target_id: 'character-board',
        isError: false,
        text: '跑完了',
        data: {
          images: [
            {
              filename: 'comfy-studio_00001_.png',
              url: 'http://127.0.0.1:8188/view?filename=comfy-studio_00001_.png&type=output'
            }
          ]
        },
        ...over
      }
    })

    /** 只有 renders/* 那两件事走自己的桩；开抽屉要问的那些保持默认。 */
    const host =
      (handlers: Record<string, unknown>): RequestStub =>
      (method, params) =>
        method in handlers
          ? typeof handlers[method] === 'function'
            ? (handlers[method] as RequestStub)(method, params)
            : handlers[method]
          : { ok: true, result: { text: '答案在此' } }

    const renderSelect = (): HTMLSelectElement =>
      document.getElementById(RENDER_ID) as HTMLSelectElement
    const runButton = (): HTMLButtonElement =>
      document.getElementById(RENDER_RUN_ID) as HTMLButtonElement
    const argBox = (name: string): HTMLInputElement =>
      document.getElementById(RENDER_ARG_PREFIX + name) as HTMLInputElement
    const imagesBox = (): HTMLInputElement | null =>
      document.getElementById(RENDER_IMAGES_ID) as HTMLInputElement | null
    const card = (): Element | null => rows('render')[0] ?? null
    const runCalls = (bridge: StudioBridge): unknown[][] =>
      bridge.request.mock.calls.filter((call: unknown[]) => call[0] === 'renders/run')

    /** 开面板 + 选目标 + 跑一遍（用例里几乎每个都要这几步）。 */
    const runOnce = async (
      handlers: Record<string, unknown> = {},
      pick = 'character-board'
    ): Promise<{ bridge: StudioBridge; card: Element | null }> => {
      const bridge = installBridge({ request: host(handlers) })
      setupDom()
      new Function(script)()
      await openPanel()
      if (pick !== '') {
        renderSelect().value = pick
        renderSelect().dispatchEvent(new Event('change'))
      }
      runButton().click()
      await flush()
      await flush()
      return { bridge, card: card() }
    }

    it('lists what the engine reported, and marks the ones whose workflow file is gone', async () => {
      installBridge({
        request: host({
          'renders/list': listing([
            target(),
            target({
              id: 'video-draft',
              title: '视频试片',
              file: '06_视频试片.json',
              fileExists: false,
              tags: ['video'],
              referenceImages: true
            })
          ])
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()

      expect(renderSelect().options).toHaveLength(2)
      // 缺文件那几条在下拉里就标出来：点下去才发现跑不起来，比提前说一句坏得多。
      expect(renderSelect().options[1]?.textContent).toBe('视频试片（工作流文件没找到）')
      expect(runButton().disabled, 'the first one is fine, so the button is usable').toBe(false)
    })

    it('asks for the parameters a workflow has no default for, and sends exactly those', async () => {
      const { bridge } = await runOnce({
        'renders/list': listing([target()]),
        'renders/run': () => runResult()
      })

      // 面板替它编一句提示词不会报错，只会出另一张图 —— 所以那个框得由用户填（见面板里那一节）。
      expect(argBox('prompt'), 'the required parameter gets a box').not.toBeNull()
      expect(runCalls(bridge), 'an empty box must not fire a render').toHaveLength(0)
      expect(document.getElementById(STATUS_ID)?.textContent).toContain('prompt')

      argBox('prompt').value = '黑衣女刺客，正面半身'
      runButton().click()
      await flush()
      await flush()

      expect(runCalls(bridge)[0]?.[1]).toEqual({
        target_id: 'character-board',
        params: { prompt: '黑衣女刺客，正面半身' }
      })
    })

    it('only sends the required ones, leaving the workflow picker values alone', async () => {
      const { bridge } = await runOnce({
        'renders/list': listing([
          target({
            params: [
              {
                name: 'prompt',
                type: 'string',
                required: true,
                default: null,
                hasDefault: false,
                description: '提示词'
              },
              {
                name: 'width',
                type: 'integer',
                required: false,
                default: 1024,
                hasDefault: true,
                description: '宽度'
              }
            ]
          })
        ]),
        'renders/run': () => runResult()
      })

      expect(argBox('width'), 'a parameter with a default is not the panel business').toBeNull()
      argBox('prompt').value = '一张侧脸'
      runButton().click()
      await flush()
      await flush()

      // 参数表里只有必填那一个：可选的一律照图上原值，面板不替它填 1024。
      expect(runCalls(bridge)[0]?.[1]).toEqual({
        target_id: 'character-board',
        params: { prompt: '一张侧脸' }
      })
    })

    it('offers the reference-image box only for the targets that take images', async () => {
      const video = target({
        id: 'video-draft',
        title: '视频试片',
        tags: ['video'],
        referenceImages: true,
        params: []
      })
      installBridge({
        request: host({ 'renders/list': listing([target(), video]) })
      })
      setupDom()
      new Function(script)()
      await openPanel()

      expect(imagesBox(), 'an image target takes no reference image').toBeNull()

      renderSelect().value = 'video-draft'
      renderSelect().dispatchEvent(new Event('change'))

      expect(imagesBox(), 'a video target can take first/last frames').not.toBeNull()
    })

    it('hands the reference images over in order, and leaves the key out when there are none', async () => {
      const video = target({
        id: 'video-draft',
        title: '视频试片',
        tags: ['video'],
        referenceImages: true,
        params: []
      })
      const { bridge } = await runOnce(
        { 'renders/list': listing([video]), 'renders/run': () => runResult() },
        'video-draft'
      )

      // 没给图就是不带这一项：带个空数组过去，读的人会以为"打算给图但没给"。
      expect(runCalls(bridge)[0]?.[1]).toEqual({ target_id: 'video-draft', params: {} })

      imagesBox()!.value = 'D:/shots/first.png; D:/shots/last.png'
      runButton().click()
      await flush()
      await flush()

      expect(runCalls(bridge)[1]?.[1]).toEqual({
        target_id: 'video-draft',
        params: {},
        images: ['D:/shots/first.png', 'D:/shots/last.png']
      })
    })

    it('shows a finished video as a video, not as a broken image', async () => {
      const video = target({
        id: 'video-draft',
        title: '视频试片',
        tags: ['video'],
        referenceImages: true,
        params: []
      })
      const { card: painted } = await runOnce(
        {
          'renders/list': listing([video]),
          // 产物不都是图：视频目标出 mp4，拿 <img> 去装它只会得到"这张图加载不出来"。
          'renders/run': () =>
            runResult({
              target_id: 'video-draft',
              data: {
                images: [
                  {
                    filename: 'shot_00001_.mp4',
                    url: 'http://127.0.0.1:8188/view?filename=shot_00001_.mp4'
                  }
                ]
              }
            })
        },
        'video-draft'
      )

      expect(painted?.querySelector('video[data-media="video"]')).not.toBeNull()
      expect(painted?.querySelector('img')).toBeNull()
      expect(painted?.textContent).toContain('shot_00001_.mp4')
    })

    it('puts the engine complaint on the card when the run itself failed', async () => {
      installBridge({
        request: host({
          'renders/list': listing([target()]),
          'renders/run': () => runResult({ isError: true, text: '显存不够：把另一张图先关掉' })
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()

      // 必填没填时那次点击不发请求，所以卡也要等填完之后才会有。
      argBox('prompt').value = '一张脸'
      runButton().click()
      await flush()
      await flush()

      const painted = card()
      expect(painted?.getAttribute('data-state')).toBe('error')
      expect(painted?.textContent).toContain('显存不够')
      expect(document.getElementById(STATUS_ID)?.textContent).toContain('失败')
    })

    it('says the workflow file is gone instead of running into a late error', async () => {
      const { bridge } = await runOnce({
        'renders/list': listing([target({ fileExists: false, params: [] })])
      })

      // 文件缺了这一趟必跑不起来（引擎那边也会报），但话说在前面，别让人等到模型加载完。
      expect(runCalls(bridge), 'nothing to run without the workflow').toHaveLength(0)
      expect(document.getElementById(STATUS_ID)?.textContent).toContain('工作流文件不在')
    })

    it('keeps the directory and the engine note on the picker instead of hiding them', async () => {
      installBridge({
        request: host({
          'renders/list': listing([target({ params: [] })], {
            workflows_dir: 'D:/comfy/user/default/workflows',
            note: '工作流目录不存在: D:/comfy/user/default/workflows'
          })
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()

      // 目标表是引擎侧代码定死的，目录整个不在时下拉里照样有 12 条 —— 那得让人看得见图该去哪儿找。
      expect(renderSelect().title).toContain('D:/comfy/user/default/workflows')
      expect(renderSelect().title).toContain('工作流目录不存在')
    })

    it('says so when the engine reported no targets at all', async () => {
      installBridge({ request: host({ 'renders/list': listing([]) }) })
      setupDom()
      new Function(script)()
      await openPanel()

      expect(renderSelect().options[0]?.textContent).toBe('（引擎没报出渲染目标）')
      expect(runButton().disabled).toBe(true)
      // 参数区也不该空着占一块地方，那看着像"漏了输入框"。
      expect((document.getElementById(RENDER_ARGS_ID) as HTMLElement).style.display).toBe('none')
    })

    it('refuses a second run while one is still going', async () => {
      const { bridge } = await runOnce({
        'renders/list': listing([target({ params: [] })]),
        // 这一趟一直挂着：渲染要占满显存好些分钟，叠着跑两边都慢（与技能那边同一个口径）。
        'renders/run': () => new Promise(() => {})
      })

      runButton().click()
      await flush()

      expect(runCalls(bridge)).toHaveLength(1)
      expect(document.getElementById(STATUS_ID)?.textContent).toContain('还在跑')
    })
  })

  describe('工作流目录（选中 + 交给对话）', () => {
    /**
     * 宿主 workflows/list 里的一份图（形状见 lib/comfy_studio/workflows.py 的 to_json）：
     * `usedBy` 为空说明这张图还没登记成渲染目标 —— 那正是这一行存在的理由。
     *
     * 注意键名与 renders/list **不一样**：那边是 snake_case 的 workflows_dir，这边是
     * workflowsDir（见 server.py 的 workflows_list）。桩按后者写，面板也得按后者取。
     */
    const entry = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
      file: '01_角色定妆板_Qwen2512.json',
      bytes: 20480,
      modified: '2026-09-20 11:02:31',
      digest: 'a'.repeat(64),
      usedBy: [],
      ...over
    })

    const listing = (files: unknown[], over: Record<string, unknown> = {}): unknown => ({
      ok: true,
      result: {
        workflowsDir: 'D:/comfy/user/default/workflows/AIGC中国风漫剧',
        note: null,
        files,
        ...over
      }
    })

    /** 只有 workflows/* 那件事走自己的桩；开抽屉要问的那些保持默认。 */
    const host =
      (handlers: Record<string, unknown>): RequestStub =>
      (method, params) =>
        method in handlers
          ? typeof handlers[method] === 'function'
            ? (handlers[method] as RequestStub)(method, params)
            : handlers[method]
          : { ok: true, result: { text: '答案在此' } }

    const picker = (): HTMLSelectElement =>
      document.getElementById(WORKFLOW_ID) as HTMLSelectElement
    const editButton = (): HTMLButtonElement =>
      document.getElementById(WORKFLOW_EDIT_ID) as HTMLButtonElement
    const newButton = (): HTMLButtonElement =>
      document.getElementById(WORKFLOW_NEW_ID) as HTMLButtonElement
    const input = (): HTMLTextAreaElement =>
      document.getElementById(INPUT_ID) as HTMLTextAreaElement
    const calls = (bridge: StudioBridge, method: string): unknown[][] =>
      bridge.request.mock.calls.filter((call: unknown[]) => call[0] === method)

    /** 开面板（默认停在对话页），顺带把下拉选到某一份上。 */
    const openWith = async (files: unknown[], pick = ''): Promise<{ bridge: StudioBridge }> => {
      const bridge = installBridge({ request: host({ 'workflows/list': listing(files) }) })
      setupDom()
      new Function(script)()
      await openPanel()
      if (pick !== '') {
        picker().value = pick
        picker().dispatchEvent(new Event('change'))
      }
      return { bridge }
    }

    it('lists every file in the directory, including the ones nothing is using yet', async () => {
      await openWith([
        entry({ usedBy: ['渲染目标 character-board'] }),
        entry({ file: '我的试验.json', bytes: 3145728 })
      ])

      // 渲染那一行只覆盖登记过的 12 张，这一行是**整个目录**：用户自己存的图也得能选出来。
      expect(picker().options).toHaveLength(2)
      expect(picker().options[1]?.textContent).toBe('我的试验.json')
      expect(picker().options[0]?.title).toContain('渲染目标 character-board')
      expect(picker().options[1]?.title).toContain('还没登记成渲染目标')
      expect(picker().options[1]?.title).toContain('3.0 MB')
    })

    it('hands the picked file to the composer, and sends nothing on its own', async () => {
      const { bridge } = await openWith([entry()])

      editButton().click()

      // 这一行的产物是一句话，不是一次写入：写图的是对话里模型手上那几把 MCP 工具。
      expect(input().value).toBe('改一下工作流「01_角色定妆板_Qwen2512.json」')
      expect(calls(bridge, 'agent/chat'), 'nothing is sent for the user').toHaveLength(0)
      expect(calls(bridge, 'workflows/list'), 'the panel only ever reads').toHaveLength(1)
      expect(document.getElementById(STATUS_ID)?.textContent).toContain('补上要改哪儿再发')
    })

    it('appends to a half-typed sentence instead of overwriting it', async () => {
      await openWith([entry()])

      input().value = '把背景换成雪天'
      editButton().click()

      expect(input().value).toBe('把背景换成雪天\n改一下工作流「01_角色定妆板_Qwen2512.json」')
    })

    it('names the picked file as the reference when making a new one', async () => {
      await openWith([entry()])

      newButton().click()

      // 新建不是改它：选中的那份只当参照，模型该建一份新的（见 workflowToChat）。
      expect(input().value).toBe('新建一份工作流，参照「01_角色定妆板_Qwen2512.json」')
    })

    it('keeps the pick across the re-read that follows every turn', async () => {
      const { bridge } = await openWith([entry({ file: 'a.json' }), entry({ file: 'b.json' })])

      picker().value = 'b.json'
      picker().dispatchEvent(new Event('change'))
      const readsBefore = calls(bridge, 'workflows/list').length

      await send('就按这个来')

      // 一轮过后模型可能刚改过或新建过一份图：清单重读一次（否则下拉停在旧世界上），
      // 但**不替用户改选择** —— 拨回第一份等于把下一步要改的那份换掉了。
      expect(calls(bridge, 'workflows/list').length).toBe(readsBefore + 1)
      expect(picker().value).toBe('b.json')
    })

    it('tells the host what the panel has picked when a turn goes out', async () => {
      const { bridge } = await openWith([entry({ file: 'a.json' }), entry({ file: 'b.json' })])

      picker().value = 'b.json'
      picker().dispatchEvent(new Event('change'))
      await send('就按这个来')

      // 选中态随这一轮带出去：没有 context，"就按这个来"里的"这个"全靠模型猜
      // （宿主把它拼进这一段的人设，见 lib/comfy_studio/panel.py）。
      expect(calls(bridge, 'agent/chat')[0]?.[1]).toMatchObject({
        text: '就按这个来',
        session_id: 'default',
        context: {
          workflow: 'b.json',
          workflows_dir: 'D:/comfy/user/default/workflows/AIGC中国风漫剧'
        }
      })
    })

    it('sends no context at all when nothing is picked', async () => {
      const { bridge } = await openWith([])

      await send('随便聊聊')

      // 空目录时下拉里只有一条 value='' 的占位项：那不是"选中了一份图"，所以**整个键都不带**
      // （老形状一字不变；宿主那边"缺这个键"与"空对象"是同一个意思）。
      expect(calls(bridge, 'agent/chat')[0]?.[1]).not.toHaveProperty('context')
    })

    it('says so when the directory has no workflow at all', async () => {
      await openWith([])

      expect(picker().options[0]?.textContent).toBe('（工作流目录里没有 .json）')
      expect(picker().disabled).toBe(true)
      expect(editButton().disabled).toBe(true)
      expect(newButton().disabled).toBe(true)
    })

    it('keeps the directory and the engine note on the picker instead of hiding them', async () => {
      installBridge({
        request: host({
          'workflows/list': listing([], {
            workflowsDir: 'D:/nowhere/workflows',
            note: '这个目录不存在；可以用 COMFY_STUDIO_WORKFLOWS 指定它'
          })
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()

      // 目录不在时清单就是空的，那得让人看得见图该去哪儿找 —— 面板照引擎说的原样写。
      expect(picker().title).toContain('D:/nowhere/workflows')
      expect(picker().title).toContain('这个目录不存在')
    })

    it('puts the failure on the picker when the host cannot read the directory', async () => {
      installBridge({
        request: host({
          'workflows/list': {
            ok: false,
            error: { code: -32603, message: '工作流清单读不了：引擎没起来' }
          }
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()

      expect(picker().options[0]?.textContent).toBe('（工作流目录里没有 .json）')
      expect(picker().title).toContain('读工作流清单失败')
      expect(picker().title).toContain('引擎没起来')
    })
  })

  describe('项目管理', () => {
    /** 项目根是宿主给的（见 lib/comfy_studio/projects.py）：面板一个路径都不拼，只照着用。 */
    const projectDir = 'D:/comfy/custom_nodes/comfy_studio/manju/projects'
    const projectPath = (name: string): string => `${projectDir}/${name}`

    /** 宿主 projects/list 里的一行。 */
    const projectRow = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
      name: '长夜',
      path: projectPath('长夜'),
      files: 3,
      missing: [],
      missing_count: 0,
      stages: [{ label: '剧本', rel: '01_剧本', files: 1, done: true, sample: [] }],
      stages_done: 1,
      stages_total: 1,
      mtime: 1758900000,
      ...over
    })

    const listing = (projects: unknown[], over: Record<string, unknown> = {}): unknown => ({
      ok: true,
      result: {
        dir: projectDir,
        exists: true,
        query: '',
        matched: projects.length,
        returned: projects.length,
        truncated: false,
        limit: 200,
        projects,
        ...over
      }
    })

    const fileRow = (rel: string, over: Record<string, unknown> = {}): Record<string, unknown> => ({
      rel,
      name: rel.split('/').slice(-1)[0],
      bytes: 2048,
      mtime: 1758900000,
      readable: true,
      ...over
    })

    /** 一个落点格（宿主 projects/tree 里 dirs 的一项）。 */
    const bucket = (rel: string, files: unknown[] = []): Record<string, unknown> => ({
      rel,
      exists: true,
      count: files.length,
      truncated: false,
      files
    })

    /**
     * 宿主 projects/tree 的回包。三格：剧本（有产物）、素材归档（空着）、项目根（一个图 + 一个 md）。
     * 「空着的那一格照样画出来」是这一页的规矩，所以它必须留在桩里。
     */
    const projectTree = (over: Record<string, unknown> = {}): unknown => ({
      ok: true,
      result: {
        name: '长夜',
        path: projectPath('长夜'),
        dirs: ['00_PROJECT/07_素材归档', '01_剧本'],
        gaps: [],
        unknown: [],
        shelves: [
          {
            key: 'script',
            title: '剧本',
            dirs: [bucket('01_剧本', [fileRow('01_剧本/总纲.md')])],
            exists: true,
            count: 1
          },
          {
            key: 'archive',
            title: '素材归档',
            dirs: [bucket('00_PROJECT/07_素材归档')],
            exists: true,
            count: 0
          },
          {
            key: 'root',
            title: '项目根',
            dirs: [],
            exists: true,
            count: 2,
            files: [
              fileRow('封面.png', { bytes: 900, readable: false }),
              fileRow('README.md', { bytes: 120 })
            ]
          }
        ],
        summary: {
          name: '长夜',
          path: projectPath('长夜'),
          files: 3,
          missing: ['02_分镜'],
          missing_count: 1,
          stages: [
            { label: '剧本', rel: '01_剧本', files: 1, done: true, sample: ['01_剧本/总纲.md'] },
            { label: '分镜', rel: '02_分镜', files: 0, done: false, sample: [] }
          ],
          stages_done: 1,
          stages_total: 2,
          mtime: 1758900000
        },
        novel: '长夜.txt',
        ...over
      }
    })

    /** 宿主 projects/read 的一页。 */
    const page = (offset: number, over: Record<string, unknown> = {}): unknown => ({
      ok: true,
      result: {
        name: '长夜',
        rel: '01_剧本/总纲.md',
        path: projectPath('长夜') + '/01_剧本/总纲.md',
        encoding: 'utf-8',
        bytes: 2048,
        total_chars: 9000,
        offset,
        requested_chars: 4000,
        chars: 4000,
        truncated: offset + 4000 < 9000,
        text: '第 ' + offset + ' 字起',
        ...over
      }
    })

    /** 只有 projects/* 那几件事走自己的桩；开抽屉时要问的那些保持默认。 */
    const host =
      (handlers: Record<string, unknown>): RequestStub =>
      (method, params) =>
        method in handlers
          ? typeof handlers[method] === 'function'
            ? (handlers[method] as RequestStub)(method, params)
            : handlers[method]
          : { ok: true, result: { text: '答案在此' } }

    const view = (id: string): HTMLElement => document.getElementById(id) as HTMLElement
    const hintLine = (): HTMLElement => view(PROJECT_HINT_ID)
    const tab = (label: string): HTMLButtonElement | undefined =>
      Array.from(document.querySelectorAll<HTMLButtonElement>(`#${TABS_ID} .cs-tab`)).find(
        (b) => b.textContent === label
      )
    const button = (text: string): HTMLButtonElement | null =>
      Array.from(document.querySelectorAll<HTMLButtonElement>(`#${PROJECT_VIEW_ID} button`)).find(
        (b) => b.textContent === text
      ) ?? null
    const projectLine = (name: string): HTMLElement | null =>
      document.querySelector<HTMLElement>(`#${PROJECT_LIST_ID} .cs-proj-row[data-name="${name}"]`)
    /** 一格：格头是「勾/空 标题 计数」三个 span，按第二个（就是标题本身）认。 */
    const shelf = (title: string): HTMLElement | null =>
      Array.from(
        document.querySelectorAll<HTMLElement>(`#${PROJECT_SHELVES_ID} .cs-proj-shelf`)
      ).find((box) => box.querySelectorAll('.cs-proj-shelf-head span')[1]?.textContent === title) ??
      null
    const fileLine = (rel: string): HTMLButtonElement | null =>
      document.querySelector<HTMLButtonElement>(
        `#${PROJECT_SHELVES_ID} .cs-proj-file[data-rel="${rel}"]`
      )
    const pagerButton = (text: string): HTMLButtonElement | null =>
      Array.from(document.querySelectorAll<HTMLButtonElement>(`#${PROJECT_PAGER_ID} button`)).find(
        (b) => b.textContent === text
      ) ?? null
    const nameInput = (): HTMLInputElement =>
      document.getElementById(PROJECT_FORM_NAME_ID) as HTMLInputElement
    const episodesInput = (): HTMLInputElement =>
      document.getElementById(PROJECT_FORM_EPISODES_ID) as HTMLInputElement
    const novelSelect = (): HTMLSelectElement =>
      document.getElementById(PROJECT_FORM_NOVEL_ID) as HTMLSelectElement
    const upgradeBox = (): HTMLInputElement =>
      document.getElementById(PROJECT_FORM_UPGRADE_ID) as HTMLInputElement
    const projectCalls = (bridge: StudioBridge, method: string): unknown[][] =>
      bridge.request.mock.calls.filter((call: unknown[]) => call[0] === method)
    /** 宿主这一趟收到的筛词（最后一次 projects/list 调用的参数）。 */
    const lastListParams = (bridge: StudioBridge): unknown =>
      projectCalls(bridge, 'projects/list').slice(-1)[0]?.[1]
    const projectFindBox = (): HTMLInputElement =>
      document.getElementById(PROJECT_FIND_ID) as HTMLInputElement
    const fileFindBox = (): HTMLInputElement =>
      document.getElementById(PROJECT_FILE_FIND_ID) as HTMLInputElement
    const reader = (): HTMLElement => view(PROJECT_READER_ID)
    const fileFindCount = (): HTMLElement => view(PROJECT_FILE_FIND_COUNT_ID)
    const hits = (): HTMLElement[] =>
      Array.from(document.querySelectorAll<HTMLElement>(`#${PROJECT_READER_ID} .cs-proj-hit`))
    /** 敲一串字进筛项目那个框，等过防抖那一小会儿。 */
    const typeProjectFind = async (text: string): Promise<void> => {
      projectFindBox().value = text
      projectFindBox().dispatchEvent(new Event('input'))
      await vi.advanceTimersByTimeAsync(300)
      await flush()
    }

    /** 一部「长夜」加一部「乙剧」，照 projects.py 的 list(query) 那样按 name 子串真的筛一遍。 */
    const filteringHost = (): RequestStub =>
      host({
        'projects/list': (_method: string, params: unknown) => {
          const name = String((params as { name?: string } | null)?.name ?? '')
          const all = [projectRow(), projectRow({ name: '乙剧', stages_done: 0, stages_total: 2 })]
          const kept = all.filter((row) => String(row.name).includes(name))
          return listing(kept, { query: name, matched: kept.length })
        }
      })

    const openProjects = async (): Promise<void> => {
      tab('项目管理')?.click()
      await flush()
    }

    const openLine = async (name: string): Promise<void> => {
      projectLine(name)?.click()
      await flush()
    }

    it('only asks the host for projects once that page is opened', async () => {
      const bridge = installBridge({ request: host({ 'projects/list': listing([]) }) })
      setupDom()
      new Function(script)()
      await openPanel()

      expect(view(CHAT_VIEW_ID).style.display).toBe('flex')
      expect(view(PROJECT_VIEW_ID).style.display).toBe('none')
      expect(
        projectCalls(bridge, 'projects/list'),
        '没打开这一页就别去翻人家的项目根'
      ).toHaveLength(0)

      await openProjects()

      expect(view(CHAT_VIEW_ID).style.display).toBe('none')
      expect(view(PROJECT_VIEW_ID).style.display).toBe('flex')
      expect(tab('项目管理')?.dataset.active).toBe('true')
      expect(tab('对话')?.dataset.active).toBe('false')
      // 项目根是宿主的事：面板连 limit 都不自己定，全按宿主的默认来。
      expect(bridge.request).toHaveBeenCalledWith('projects/list', {})
    })

    it('says the project root is not there yet instead of painting a failure', async () => {
      installBridge({ request: host({ 'projects/list': listing([], { exists: false }) }) })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()

      // 目录没建不是错误：说明写在列表里，指人去建第一部，而不是弹一个"读取失败"。
      expect(document.getElementById(PROJECT_LIST_ID)?.textContent).toContain('还没建过项目')
      expect(document.getElementById(PROJECT_LIST_ID)?.textContent).toContain(projectDir)
      expect(hintLine().getAttribute('data-tone')).not.toBe('error')
    })

    it('lists the projects, then opens one into one shelf per drop point', async () => {
      const bridge = installBridge({
        request: host({
          'projects/list': listing([
            projectRow(),
            projectRow({ name: '乙剧', stages_done: 0, stages_total: 2 })
          ]),
          'projects/tree': projectTree()
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()

      expect(document.querySelectorAll(`#${PROJECT_LIST_ID} .cs-proj-row`)).toHaveLength(2)
      // 列表只报数，不自己算完成度：阶段判据是宿主按落点里有没有产物判的。
      expect(projectLine('长夜')?.textContent).toContain('1/1 段')
      expect(projectLine('乙剧')?.textContent).toContain('0/2 段')

      await openLine('长夜')

      expect(bridge.request).toHaveBeenCalledWith('projects/tree', { name: '长夜' })
      expect(document.getElementById(PROJECT_HEAD_ID)?.textContent).toContain('长夜')
      expect(document.getElementById(PROJECT_HEAD_ID)?.textContent).toContain('原著：长夜.txt')
      // 三个格子都画出来（含空着那个），不是只画有产物的。
      expect(document.querySelectorAll(`#${PROJECT_SHELVES_ID} .cs-proj-shelf`)).toHaveLength(3)
      expect(shelf('剧本')?.dataset.empty, '有产物').toBe('0')
      expect(shelf('素材归档')?.dataset.empty, '空着也要占一格，人才知道这戏还缺这摞资料').toBe('1')
      expect(shelf('素材归档')?.textContent).toContain('还空着')
      expect(projectLine('长夜')?.dataset.open).toBe('true')
    })

    it('splits a shelf by granularity, and only when there are two sides to tell apart', async () => {
      const meta = bucket('00_PROJECT/01_剧本/00_总纲', [
        fileRow('00_PROJECT/01_剧本/00_总纲/角色小传.md')
      ])
      const episodeRel = '00_PROJECT/01_剧本'
      const episodes = bucket(episodeRel, [fileRow(episodeRel + '/EP01-剧本.md')])
      installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'projects/tree': projectTree({
            shelves: [
              {
                key: 'script',
                title: '剧本与总纲',
                dirs: [episodes, meta],
                groups: [
                  { scope: '全剧级', title: '全剧级', dirs: [meta], exists: true, count: 1 },
                  { scope: '分集级', title: '分集级', dirs: [episodes], exists: true, count: 1 }
                ],
                exists: true,
                count: 2
              },
              {
                key: 'archive',
                title: '素材归档',
                dirs: [
                  bucket('00_PROJECT/07_素材归档', [
                    fileRow('00_PROJECT/07_素材归档/素材来源登记.md')
                  ])
                ],
                groups: [
                  {
                    scope: '全剧级',
                    title: '全剧级',
                    dirs: [
                      bucket('00_PROJECT/07_素材归档', [
                        fileRow('00_PROJECT/07_素材归档/素材来源登记.md')
                      ])
                    ],
                    exists: true,
                    count: 1
                  }
                ],
                exists: true,
                count: 1
              }
            ]
          })
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()
      await openLine('长夜')

      // 两种粒度混在一列里，读的人分不出哪份该跟着集数走 —— 一格才分节。
      const groups = Array.from(
        shelf('剧本与总纲')?.querySelectorAll<HTMLElement>('.cs-proj-group') ?? []
      )
      expect(groups.map((box) => box.dataset.scope)).toEqual(['全剧级', '分集级'])
      expect(groups[0]?.textContent).toContain('1 个文件')
      // 分节只是摆法：文件行照旧都在（点得开那一下不能丢）。
      expect(fileLine('00_PROJECT/01_剧本/00_总纲/角色小传.md')).not.toBeNull()
      expect(fileLine('00_PROJECT/01_剧本/EP01-剧本.md')).not.toBeNull()

      // 一格本来就只有一边时，不摆小标题：一条"全剧级"标题底下全是全剧级，那是噪声。
      const flat = Array.from(
        shelf('素材归档')?.querySelectorAll<HTMLElement>('.cs-proj-group') ?? []
      )
      expect(flat).toHaveLength(0)
    })

    it('lists a file it cannot read but keeps it a dead row', async () => {
      installBridge({
        request: host({ 'projects/list': listing([projectRow()]), 'projects/tree': projectTree() })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()
      await openLine('长夜')

      // 图片、音频、视频躺在格子里就照样列出来，但不给点：读成文本只会是一片乱码。
      expect(fileLine('封面.png'), '图也列出来').not.toBeNull()
      expect(fileLine('封面.png')?.disabled).toBe(true)
      expect(fileLine('README.md')?.disabled).toBe(false)
    })

    it('keeps the spec gaps apart from the missing drop points', async () => {
      installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'projects/tree': projectTree({ gaps: ['02_分镜'], unknown: ['09_旧落点'] })
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()
      await openLine('长夜')

      const head = document.getElementById(PROJECT_HEAD_ID)?.textContent ?? ''
      // 缺落点是"去补目录"，对不上是"面板自己有 bug"：两码事，不能混成一句话。
      expect(head).toContain('缺 1 个落点：02_分镜')
      expect(head).toContain('规范里有落点没被面板归到任何一格：02_分镜')
      expect(head).toContain('面板写了规范里没有的落点：09_旧落点')
    })

    it('pages a file by character offset and pages back by the size it asked for', async () => {
      const bridge = installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'projects/tree': projectTree(),
          'projects/read': (_method: string, params: unknown) => {
            const asked = (params as { offset: number }).offset
            // 末页短读：只回 1000 字，但"这一页本来要多少"仍是 4000 —— 往回翻要按 4000 算。
            if (asked === 8000) return page(8000, { chars: 1000, truncated: false, text: '末页' })
            return page(asked)
          }
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()
      await openLine('长夜')

      fileLine('01_剧本/总纲.md')?.click()
      await flush()

      // 不带 chars：一页多少字按宿主那份来。
      expect(bridge.request).toHaveBeenCalledWith('projects/read', {
        name: '长夜',
        rel: '01_剧本/总纲.md',
        offset: 0
      })
      expect(view(PROJECT_READER_ID).textContent).toBe('第 0 字起')
      expect(pagerButton('上一页')?.disabled, '第一页没有上一页').toBe(true)
      expect(pagerButton('下一页')?.disabled).toBe(false)

      pagerButton('下一页')?.click()
      await flush()
      pagerButton('下一页')?.click()
      await flush()

      expect(view(PROJECT_READER_ID).textContent).toBe('末页')
      expect(pagerButton('下一页')?.disabled, '读到头了').toBe(true)

      pagerButton('上一页')?.click()
      await flush()

      // 8000 - 4000（这一页 requested_chars），不是 8000 - 1000（这一页实际回了多少字）。
      expect(bridge.request).toHaveBeenCalledWith('projects/read', {
        name: '长夜',
        rel: '01_剧本/总纲.md',
        offset: 4000
      })
    })

    it('drops a tree that came back after the user switched to another project', async () => {
      let late: (value: unknown) => void = () => {}
      installBridge({
        request: host({
          'projects/list': listing([projectRow(), projectRow({ name: '乙剧' })]),
          'projects/tree': (_method: string, params: unknown) => {
            const name = (params as { name: string }).name
            if (name === '长夜')
              return new Promise((resolve) => {
                late = resolve
              })
            // 乙剧没登记原著：这里留空，好让"长夜"这个名字只可能来自那一趟迟到的回话。
            return projectTree({ name: '乙剧', path: projectPath('乙剧'), novel: '' })
          }
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()

      projectLine('长夜')?.click()
      await flush()
      await openLine('乙剧')
      expect(document.getElementById(PROJECT_HEAD_ID)?.textContent).toContain('乙剧')

      late(projectTree())
      await flush()

      // 先发的后回来：不丢就等于把用户刚打开的乙剧盖成长夜。
      expect(document.getElementById(PROJECT_HEAD_ID)?.textContent).toContain('乙剧')
      expect(document.getElementById(PROJECT_HEAD_ID)?.textContent).not.toContain('长夜')
    })

    it('draws how many stages already have output on each project line', async () => {
      installBridge({
        request: host({
          'projects/list': listing([projectRow({ stages_done: 2, stages_total: 4 })])
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()

      expect(
        projectLine('长夜')?.querySelector<HTMLElement>('.cs-proj-meter-fill')?.style.width
      ).toBe('50.00%')
      // 条上写的是宿主的两个数（projects/tree 的 summary），不是面板自己算的"完成度"。
      expect(projectLine('长夜')?.querySelector('.cs-proj-meter')?.getAttribute('title')).toBe(
        '2/4 段有产物'
      )
    })

    it('says how far this project is and which step is next', async () => {
      installBridge({
        request: host({ 'projects/list': listing([projectRow()]), 'projects/tree': projectTree() })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()
      await openLine('长夜')

      const head = view(PROJECT_HEAD_ID)
      expect(
        head.querySelector<HTMLElement>('.cs-proj-meter-fill')?.style.width,
        '剧本有产物、分镜没有'
      ).toBe('50.00%')
      expect(head.querySelector('.cs-proj-meter')?.getAttribute('title')).toBe('1/2 段有产物')
      // 下一步是哪一步照宿主给的阶段顺序念（stages[].label），面板不自己排工序。
      expect(head.textContent).toContain('下一步：分镜')
    })

    it('walks from a project to the novel it was built from', async () => {
      const bridge = installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'projects/tree': projectTree(),
          'novels/chapters': {
            ok: true,
            result: {
              name: '长夜.txt',
              count: 0,
              returned: 0,
              total_chars: 9000,
              limit: 5000,
              message: '',
              chapters: []
            }
          },
          'novels/read': (_method: string, params: unknown) => ({
            ok: true,
            result: {
              name: '长夜.txt',
              offset: (params as { offset: number }).offset,
              chars: 4000,
              requested_chars: 4000,
              total_chars: 9000,
              at_end: false,
              text: '正文在这儿'
            }
          })
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()
      await openLine('长夜')

      const head = view(PROJECT_HEAD_ID)
      expect(head.textContent).toContain('原著：长夜.txt')
      const go = Array.from(head.querySelectorAll<HTMLButtonElement>('button')).find(
        (b) => b.textContent === '去读原文'
      )
      expect(go, '登记了原著就该有一条路过去').toBeDefined()

      go?.click()
      await flush()

      expect(view(NOVEL_VIEW_ID).style.display).toBe('flex')
      expect(bridge.request).toHaveBeenCalledWith('novels/read', { name: '长夜.txt', offset: 0 })
      expect(view(NOVEL_READER_ID).textContent).toBe('正文在这儿')
    })

    it('says the source novel is gone from the library instead of pretending it is there', async () => {
      const bridge = installBridge({
        request: host({
          'novels/list': { ok: true, result: { novels: [] } },
          'novels/chapters': {
            ok: true,
            result: {
              name: '长夜.txt',
              count: 0,
              returned: 0,
              total_chars: 9000,
              limit: 5000,
              message: '',
              chapters: []
            }
          },
          'novels/read': { ok: false, error: { message: '书库里没有长夜.txt' } },
          'projects/list': listing([projectRow()]),
          'projects/tree': projectTree()
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()

      // 先真的列过一次原文库：没列过的话面板只知道"还没问过"，不能替它下"没有这一篇"的结论。
      tab('管理小说')?.click()
      await flush()
      tab('项目管理')?.click()
      await flush()
      await openLine('长夜')

      const head = view(PROJECT_HEAD_ID)
      expect(head.textContent).toContain('原文库里没这一篇')
      const go = Array.from(head.querySelectorAll<HTMLButtonElement>('button')).find(
        (b) => b.textContent === '去看看原文库'
      )
      expect(go).toBeDefined()

      go?.click()
      await flush()

      // 路照样铺过去：到底有没有这一篇由宿主说，面板不在这儿自己编一个结论。
      expect(bridge.request).toHaveBeenCalledWith('novels/read', { name: '长夜.txt', offset: 0 })
      expect(view(NOVEL_READER_ID).textContent).toContain('读不了这一篇')
      expect(view(NOVEL_HINT_ID).textContent).toContain('读不了 长夜.txt')
    })

    it('refuses a nameless project and a nonsense episode count without asking the host', async () => {
      const bridge = installBridge({
        request: host({
          'projects/list': listing([]),
          'novels/list': { ok: true, result: { novels: [] } }
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()

      button('新建项目…')?.click()
      await flush()

      button('建')?.click()
      await flush()
      expect(hintLine().textContent).toContain('先给这部戏起个名字')
      expect(hintLine().getAttribute('data-tone')).toBe('error')

      nameInput().value = '长夜'
      episodesInput().value = '0'
      button('建')?.click()
      await flush()
      expect(hintLine().textContent).toContain('集数要是 1 以上的整数')

      expect(
        projectCalls(bridge, 'projects/create'),
        '本地就问得出的错，别拿去打扰宿主'
      ).toHaveLength(0)
    })

    it('closes the new-project popup by the backdrop, Esc and 取消', async () => {
      installBridge({
        request: host({
          'projects/list': listing([]),
          'novels/list': { ok: true, result: { novels: [] } }
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()

      const popup = (): HTMLElement => view(PROJECT_FORM_ID)
      expect(popup().dataset.open, '平时是收着的（它就压在页面上面，不该常驻）').toBe('0')

      button('新建项目…')?.click()
      await flush()
      expect(popup().dataset.open).toBe('1')

      // 暗底就是弹窗那一层自己：点它（事件落在它身上）＝退出，不该只能去够那颗「取消」。
      popup().dispatchEvent(new MouseEvent('click', { bubbles: true }))
      expect(popup().dataset.open).toBe('0')

      button('新建项目…')?.click()
      await flush()
      // Esc 从卡片里冒上来：打开时光标就在剧名那一格（见 toggleProjectForm）。
      nameInput().dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
      expect(popup().dataset.open).toBe('0')

      button('新建项目…')?.click()
      await flush()
      button('取消')?.click()
      expect(popup().dataset.open, '取消只管关，不建目录').toBe('0')
    })

    it('creates a project with the linked novel and opens it right away', async () => {
      const bridge = installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'novels/list': {
            ok: true,
            result: { novels: [{ name: '长夜.txt', bytes: 2048, mtime: 1, text: true }] }
          },
          'projects/create': {
            ok: true,
            result: {
              name: '长夜',
              path: projectPath('长夜'),
              episodes: 12,
              upgrade: false,
              dirs: ['01_剧本'],
              files: ['01_剧本/总纲.md'],
              skipped: [],
              pending: [],
              novel: {
                name: '长夜',
                novel: '长夜.txt',
                file: '',
                linked: true,
                already: false,
                current: '',
                reason: 'filled'
              }
            }
          },
          'projects/tree': projectTree()
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()

      button('新建项目…')?.click()
      await flush()
      expect(novelSelect().options[0]?.textContent).toBe('（不登记原著）')
      expect(
        Array.from(novelSelect().options).map((o) => o.value),
        '原著下拉是从原文库现取的'
      ).toContain('长夜.txt')

      nameInput().value = '长夜'
      novelSelect().value = '长夜.txt'
      upgradeBox().checked = true
      button('建')?.click()
      await flush()

      expect(bridge.request).toHaveBeenCalledWith('projects/create', {
        name: '长夜',
        episodes: 12,
        upgrade: true,
        novel: '长夜.txt'
      })
      expect(hintLine().textContent).toContain('建好了 长夜（新目录 1 个，新文件 1 份）')
      expect(hintLine().textContent).toContain('原著登记为「长夜.txt」')
      expect(view(PROJECT_FORM_ID).dataset.open, '建完把表单收起来，接着看它的落点').toBe('0')
      expect(document.getElementById(PROJECT_HEAD_ID)?.textContent).toContain(projectPath('长夜'))
    })

    it('explains each way the novel link did not happen', async () => {
      const createWith = (novel: Record<string, unknown>): unknown => ({
        ok: true,
        result: {
          name: '长夜',
          path: projectPath('长夜'),
          episodes: 12,
          upgrade: false,
          dirs: [],
          files: [],
          skipped: [],
          pending: [],
          novel
        }
      })
      installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'projects/tree': projectTree(),
          'projects/create': createWith({
            name: '长夜',
            novel: '长夜.txt',
            linked: false,
            already: true,
            current: '另一本.txt',
            reason: 'already'
          })
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()
      button('新建项目…')?.click()
      await flush()

      nameInput().value = '长夜'
      button('建')?.click()
      await flush()

      // 来源记录不许被悄悄改掉：已经填着的时候要说出原来填的是什么。
      expect(hintLine().textContent).toContain('没动它')
      expect(hintLine().textContent).toContain('另一本.txt')
    })

    it('puts the brief in the composer without sending it', async () => {
      const bridge = installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'projects/tree': projectTree(),
          'projects/brief': {
            ok: true,
            result: {
              name: '长夜',
              path: projectPath('长夜'),
              text: '【项目】长夜\n阶段：✅ 剧本  ☐ 分镜'
            }
          }
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()
      await openLine('长夜')

      button('发到对话')?.click()
      await flush()

      expect(bridge.request).toHaveBeenCalledWith('projects/brief', { name: '长夜' })
      expect(view(CHAT_VIEW_ID).style.display, '拿去对话就切回对话').toBe('flex')
      expect((document.getElementById(INPUT_ID) as HTMLTextAreaElement).value).toContain(
        '【项目】长夜'
      )
      // 拿哪一部开工、怎么开工是用户的事：面板只把材料放进框里，不替他按发送。
      expect(projectCalls(bridge, 'agent/chat')).toHaveLength(0)
      expect(document.getElementById(STATUS_ID)?.textContent).toContain('长夜')
    })

    it('says the project could not be read when the host refuses', async () => {
      installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'projects/tree': { ok: false, error: { message: '找不到项目规范的事实源' } }
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()
      await openLine('长夜')

      expect(document.getElementById(PROJECT_HEAD_ID)?.textContent).toContain(
        '找不到项目规范的事实源'
      )
      expect(
        document.querySelectorAll(`#${PROJECT_SHELVES_ID} .cs-proj-shelf`),
        '读不出来就别摆格子'
      ).toHaveLength(0)
      expect(hintLine().getAttribute('data-tone')).toBe('error')
    })

    it('filters projects through the host instead of hiding the ones it never listed', async () => {
      const bridge = installBridge({ request: filteringHost() })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()
      expect(
        document.querySelectorAll(`#${PROJECT_LIST_ID} .cs-proj-row`),
        '不带筛词时两部都在'
      ).toHaveLength(2)

      await typeProjectFind('乙')

      // 筛词是交给宿主去匹配的（projects.py 的 list(query)）：面板手里那一屏本来就可能被截断，
      // 自己再过滤一遍，没列出来的那几部就永远看不见了。
      expect(lastListParams(bridge)).toEqual({ name: '乙' })
      expect(document.querySelectorAll(`#${PROJECT_LIST_ID} .cs-proj-row`)).toHaveLength(1)
      expect(projectLine('乙剧')).not.toBeNull()
      expect(projectLine('长夜')).toBeNull()
      expect(document.getElementById(PROJECT_FIND_COUNT_ID)?.textContent).toBe('匹配 1 部')
    })

    it('counts what the host actually matched, not what fits on the screen', async () => {
      const bridge = installBridge({
        request: host({
          'projects/list': listing([projectRow(), projectRow({ name: '乙剧' })], {
            matched: 37,
            returned: 2,
            truncated: true,
            limit: 2
          })
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()

      // matched 是宿主筛完之后的匹配数：面板不自己数屏上那两行报成"共 2 部"。
      expect(document.getElementById(PROJECT_FIND_COUNT_ID)?.textContent).toBe('共 37 部')
      expect(document.getElementById(PROJECT_LIST_ID)?.textContent).toContain('还有 35 部没列出来')
      // 筛词写细一点就能把它捞出来 —— 这句得说，否则人会以为项目丢了。
      expect(document.getElementById(PROJECT_LIST_ID)?.textContent).toContain('把名字写细一点')
      expect(bridge.request).toHaveBeenCalledWith('projects/list', {})
    })

    it('says no project matches instead of looking like an empty project root', async () => {
      installBridge({ request: filteringHost() })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()

      await typeProjectFind('丙')

      expect(document.getElementById(PROJECT_LIST_ID)?.textContent).toContain(
        '没有名字含「丙」的项目'
      )
      expect(document.getElementById(PROJECT_FIND_COUNT_ID)?.textContent).toBe('匹配 0 部')
      // 筛不着 ≠ 目录里还没东西：这两句话不能混着说。
      expect(document.getElementById(PROJECT_LIST_ID)?.textContent).not.toContain('还没建过项目')
    })

    it('waits for a pause in typing before asking the host again', async () => {
      const bridge = installBridge({ request: filteringHost() })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()
      expect(projectCalls(bridge, 'projects/list'), '开页那一趟').toHaveLength(1)

      projectFindBox().value = '乙'
      projectFindBox().dispatchEvent(new Event('input'))
      projectFindBox().value = '乙剧'
      projectFindBox().dispatchEvent(new Event('input'))
      await vi.advanceTimersByTimeAsync(100)
      expect(projectCalls(bridge, 'projects/list'), '手还没停，先别问').toHaveLength(1)

      await vi.advanceTimersByTimeAsync(200)
      await flush()

      expect(projectCalls(bridge, 'projects/list')).toHaveLength(2)
      expect(lastListParams(bridge), '只发最后停下来的那一串').toEqual({ name: '乙剧' })
    })

    it('clears the filter with Escape and lists everything again', async () => {
      const bridge = installBridge({ request: filteringHost() })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()
      await typeProjectFind('乙')
      expect(document.getElementById(PROJECT_FIND_COUNT_ID)?.textContent).toBe('匹配 1 部')

      projectFindBox().dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Escape', cancelable: true })
      )
      await flush()

      expect(lastListParams(bridge)).toEqual({})
      expect(projectFindBox().value).toBe('')
      expect(document.getElementById(PROJECT_FIND_COUNT_ID)?.textContent).toBe('共 2 部')
    })

    it('drops the filter when a project is built, so the new one shows up', async () => {
      const rows = [projectRow({ name: '甲' }), projectRow({ name: '乙剧' })]
      const bridge = installBridge({
        request: host({
          'projects/list': (_method: string, params: unknown) => {
            const name = String((params as { name?: string } | null)?.name ?? '')
            const kept = rows.filter((row) => String(row.name).includes(name))
            return listing(kept, { query: name, matched: kept.length })
          },
          'projects/create': {
            ok: true,
            result: {
              name: '新戏',
              path: projectPath('新戏'),
              episodes: 12,
              upgrade: false,
              dirs: [],
              files: [],
              skipped: [],
              pending: [],
              novel: null
            }
          },
          'projects/tree': (_method: string, params: unknown) =>
            projectTree({ name: (params as { name: string }).name })
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()
      await typeProjectFind('乙')
      expect(projectLine('甲')).toBeNull()
      const before = projectCalls(bridge, 'projects/list').length

      button('新建项目…')?.click()
      await flush()
      nameInput().value = '新戏'
      button('建')?.click()
      await flush()

      // 筛词跟着这次新建一起清掉：留着的话重列还是带着「乙」，刚建好的那部名字对不上，
      // 用户建完就"看不见自己"。清的是状态与输入框，不带出额外一趟请求。
      expect(projectFindBox().value).toBe('')
      expect(lastListParams(bridge)).toEqual({})
      expect(projectCalls(bridge, 'projects/list')).toHaveLength(before + 1)
    })

    it('adds the whole screen up instead of making the user count rows', async () => {
      installBridge({
        request: host({
          'projects/list': listing([
            projectRow({ name: '甲', stages_done: 0, stages_total: 2, missing_count: 2 }),
            projectRow({ name: '乙', stages_done: 1, stages_total: 2, missing_count: 1 }),
            projectRow({ name: '丙', stages_done: 2, stages_total: 2, missing_count: 0 })
          ])
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()

      const text = view(PROJECT_OVERVIEW_ID).textContent ?? ''
      // 这几个数全部出自宿主每一行自带的字段（stages_done / stages_total / missing_count）。
      expect(text).toContain('列出来的 3 部')
      expect(text).toContain('还没动工 1 部')
      expect(text).toContain('进行中 1 部')
      expect(text).toContain('阶段全落齐 1 部')
      expect(text).toContain('阶段合计 3/6')
      expect(text).toContain('缺落点共 3 格')
      // 阶段全落齐 ≠ 这部戏做完了：这一行不越界替宿主下结论。
      expect(text).not.toContain('做完')
    })

    it('says the overview only counted the ones it was shown', async () => {
      installBridge({
        request: host({
          'projects/list': listing([projectRow()], {
            matched: 8,
            returned: 1,
            truncated: true,
            limit: 1
          })
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()

      const text = view(PROJECT_OVERVIEW_ID).textContent ?? ''
      expect(text).toContain('列出来的 1 部')
      expect(text).toContain('还有 7 部没算进来')
    })

    it('keeps the overview out of the way when there is nothing to add up', async () => {
      installBridge({ request: host({ 'projects/list': listing([]) }) })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()

      expect(view(PROJECT_OVERVIEW_ID).textContent).toBe('')
    })

    it('finds a word inside the page it already read, and marks every hit', async () => {
      const bridge = installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'projects/tree': projectTree(),
          'projects/read': page(0, {
            text: '长夜漫漫，长夜里的灯。',
            total_chars: 11,
            truncated: false
          })
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()
      await openLine('长夜')
      fileLine('01_剧本/总纲.md')?.click()
      await flush()

      fileFindBox().value = '长夜'
      fileFindBox().dispatchEvent(new Event('input'))
      await flush()

      expect(hits(), '两处「长夜」都得上记号').toHaveLength(2)
      expect(hits()[0]?.getAttribute('data-cur'), '当前停在这一处').toBe('true')
      expect(hits()[1]?.getAttribute('data-cur')).toBeNull()
      expect(fileFindCount().textContent).toBe('1/2 处')
      // 上记号不该改动正文：屏幕上的字仍然是宿主给的那一份。
      expect(reader().textContent).toBe('长夜漫漫，长夜里的灯。')
      // 页内找字只在屏幕上转，不再去读一趟（projects/read 没有搜索参数，见 projects.py 的 read）。
      expect(projectCalls(bridge, 'projects/read')).toHaveLength(1)

      document.getElementById(PROJECT_FILE_FIND_NEXT_ID)?.click()
      await flush()
      expect(hits()[1]?.getAttribute('data-cur')).toBe('true')
      expect(fileFindCount().textContent).toBe('2/2 处')

      // 到底了绕回第一处
      document.getElementById(PROJECT_FILE_FIND_NEXT_ID)?.click()
      await flush()
      expect(fileFindCount().textContent).toBe('1/2 处')

      // 上一处往前绕：从第一处往上就是最后一处
      document.getElementById(PROJECT_FILE_FIND_PREV_ID)?.click()
      await flush()
      expect(fileFindCount().textContent).toBe('2/2 处')

      document.getElementById(PROJECT_FILE_FIND_CLEAR_ID)?.click()
      await flush()
      expect(hits()).toHaveLength(0)
      expect(fileFindCount().textContent).toBe('')
      expect(fileFindBox().value).toBe('')
      expect(reader().textContent).toBe('长夜漫漫，长夜里的灯。')
    })

    it('keeps the original spelling of what it found', async () => {
      installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'projects/tree': projectTree(),
          'projects/read': page(0, {
            text: 'Draft one, draft two.',
            total_chars: 20,
            truncated: false
          })
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()
      await openLine('长夜')
      fileLine('01_剧本/总纲.md')?.click()
      await flush()

      fileFindBox().value = 'DRAFT'
      fileFindBox().dispatchEvent(new Event('input'))
      await flush()

      expect(hits()).toHaveLength(2)
      // 屏幕上是文件里本来的写法，不是输入框里那串大写。
      expect(hits()[0]?.textContent).toBe('Draft')
      expect(hits()[1]?.textContent).toBe('draft')
    })

    it('says it found nothing without touching the text', async () => {
      installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'projects/tree': projectTree(),
          'projects/read': page(0, {
            text: '长夜漫漫，长夜里的灯。',
            total_chars: 11,
            truncated: false
          })
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()
      await openLine('长夜')
      fileLine('01_剧本/总纲.md')?.click()
      await flush()

      fileFindBox().value = '没有这三个字'
      fileFindBox().dispatchEvent(new Event('input'))
      await flush()

      expect(hits()).toHaveLength(0)
      expect(fileFindCount().textContent).toBe('没找到')
      expect(fileFindCount().dataset.tone).toBe('error')
      expect(reader().textContent, '没找着就把正文原样还回去').toBe('长夜漫漫，长夜里的灯。')
    })

    it('walks the hits with Enter and Shift+Enter', async () => {
      installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'projects/tree': projectTree(),
          'projects/read': page(0, {
            text: '长夜漫漫，长夜里的灯。',
            total_chars: 11,
            truncated: false
          })
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()
      await openLine('长夜')
      fileLine('01_剧本/总纲.md')?.click()
      await flush()

      fileFindBox().value = '长夜'
      fileFindBox().dispatchEvent(new Event('input'))
      await flush()

      fileFindBox().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', cancelable: true }))
      await flush()
      expect(fileFindCount().textContent).toBe('2/2 处')

      fileFindBox().dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', shiftKey: true, cancelable: true })
      )
      await flush()
      expect(fileFindCount().textContent, 'Shift+Enter 往回走').toBe('1/2 处')

      fileFindBox().dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', cancelable: true }))
      await flush()
      expect(fileFindBox().value).toBe('')
      expect(fileFindCount().textContent).toBe('')
    })

    it('counts hits again for the page it just turned to', async () => {
      installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'projects/tree': projectTree(),
          'projects/read': (_method: string, params: unknown) => {
            const asked = (params as { offset: number }).offset
            return asked === 0
              ? page(0, { text: '长夜里', total_chars: 6000, truncated: true })
              : page(asked, { text: '这一页没有那两个字', total_chars: 6000, truncated: false })
          }
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()
      await openLine('长夜')
      fileLine('01_剧本/总纲.md')?.click()
      await flush()

      fileFindBox().value = '长夜'
      fileFindBox().dispatchEvent(new Event('input'))
      await flush()
      expect(fileFindCount().textContent).toBe('1/1 处')

      pagerButton('下一页')?.click()
      await flush()

      expect(reader().textContent).toBe('这一页没有那两个字')
      expect(hits(), '上一页数到的第几处跟这一页没关系').toHaveLength(0)
      expect(fileFindCount().textContent).toBe('没找到')
    })

    it('drops the old hits when another project is opened', async () => {
      installBridge({
        request: host({
          'projects/list': listing([projectRow(), projectRow({ name: '乙剧' })]),
          'projects/tree': (_method: string, params: unknown) =>
            projectTree({ name: (params as { name: string }).name }),
          'projects/read': page(0, {
            text: '长夜漫漫，长夜里的灯。',
            total_chars: 11,
            truncated: false
          })
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openProjects()
      await openLine('长夜')
      fileLine('01_剧本/总纲.md')?.click()
      await flush()

      fileFindBox().value = '长夜'
      fileFindBox().dispatchEvent(new Event('input'))
      await flush()
      expect(hits()).toHaveLength(2)

      await openLine('乙剧')

      // 另一部戏的正文还没读出来，屏上不能留着上一部的那一页给这一部背书。
      expect(hits()).toHaveLength(0)
      expect(reader().textContent).toContain('点一格里的文件名')
      expect(fileFindCount().textContent).toBe('')
      expect(fileFindBox().value, '框里那串字留着，等新文件读出来自然会对上').toBe('长夜')
    })
  })

  describe('流水线', () => {
    /** 宿主 projects/list 里的一行。这一页只借它填下拉，别的栏用不上。 */
    const projectRow = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
      name: '长夜',
      path: 'D:/comfy/custom_nodes/comfy_studio/manju/projects/长夜',
      files: 3,
      missing: [],
      missing_count: 0,
      stages: [],
      stages_done: 1,
      stages_total: 1,
      mtime: 1758900000,
      ...over
    })

    const listing = (projects: unknown[]): unknown => ({
      ok: true,
      result: {
        dir: 'D:/comfy/custom_nodes/comfy_studio/manju/projects',
        exists: true,
        query: '',
        matched: projects.length,
        returned: projects.length,
        truncated: false,
        limit: 200,
        projects
      }
    })

    /**
     * pipeline/plan 里的一段。栏名照 lib/comfy_studio/pipeline.py 的 plan_payload 抄 ——
     * 面板画的就是那几栏，名字对不上就成了一条永远空着的行。
     */
    const stage = (code: string, over: Record<string, unknown> = {}): Record<string, unknown> => ({
      code,
      name: code + ' 那一段',
      owner: 'script',
      agent: 'studio-script',
      actor: '剧本智能体',
      artifact: '落点-' + code,
      needs_render: false,
      brief: '',
      check_dirs: [],
      check_exts: [],
      ...over
    })

    /** 三段的计划：S2 跑完还得回引擎侧出图。 */
    const planStages = (): Record<string, unknown>[] => [
      stage('S0'),
      stage('S1'),
      stage('S2', { needs_render: true, actor: '分镜智能体' })
    ]

    const plan = (over: Record<string, unknown> = {}): unknown => ({
      ok: true,
      result: {
        project: '长夜',
        novel: '长夜.txt',
        stages: planStages(),
        state: {},
        render_required: ['S2'],
        ...over
      }
    })

    /** 只有流水线那几件事走自己的桩；开抽屉时要问的那些保持默认。 */
    const host =
      (handlers: Record<string, unknown>): RequestStub =>
      (method, params) =>
        method in handlers
          ? typeof handlers[method] === 'function'
            ? (handlers[method] as RequestStub)(method, params)
            : handlers[method]
          : { ok: true, result: { text: '答案在此' } }

    const view = (id: string): HTMLElement => document.getElementById(id) as HTMLElement
    const hint = (): HTMLElement => view(PIPELINE_HINT_ID)
    const tab = (label: string): HTMLButtonElement | undefined =>
      Array.from(document.querySelectorAll<HTMLButtonElement>(`#${TABS_ID} .cs-tab`)).find(
        (b) => b.textContent === label
      )
    const barButton = (text: string): HTMLButtonElement | null =>
      Array.from(
        document.querySelectorAll<HTMLButtonElement>(`#${PIPELINE_VIEW_ID} .cs-proj-bar button`)
      ).find((b) => b.textContent === text) ?? null
    const formButton = (text: string): HTMLButtonElement | null =>
      Array.from(document.querySelectorAll<HTMLButtonElement>(`#${PIPELINE_FORM_ID} button`)).find(
        (b) => b.textContent === text
      ) ?? null
    const card = (code: string): HTMLElement | null =>
      document.querySelector<HTMLElement>(
        `#${PIPELINE_LIST_ID} .cs-pipe-stage[data-code="${code}"]`
      )
    const cards = (): HTMLElement[] =>
      Array.from(document.querySelectorAll<HTMLElement>(`#${PIPELINE_LIST_ID} .cs-pipe-stage`))
    const asks = (bridge: StudioBridge, method: string): unknown[][] =>
      bridge.request.mock.calls.filter((call: unknown[]) => call[0] === method)

    /** 宿主 renders/list 里的一条目标（形状见 lib/comfy_studio/renders/catalog.py 的 to_json）。 */
    const renderTarget = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
      id: 'character-sheet',
      title: '角色定妆板（Qwen-Image 2512）',
      file: '01_角色定妆板_Qwen2512.json',
      fileExists: true,
      tags: ['image'],
      referenceImages: false,
      params: [],
      ...over
    })

    const renders = (targets: unknown[]): unknown => ({
      ok: true,
      result: {
        workflows_dir: 'D:/comfy/user/default/workflows/AIGC中国风漫剧',
        note: null,
        targets
      }
    })

    /** 阶段卡上那排「去出图」（宿主绑了图才有这排，见注入脚本的 pipeRenderRow）。 */
    const renderButtons = (code: string): HTMLButtonElement[] =>
      Array.from(
        card(code)?.querySelectorAll<HTMLButtonElement>('.cs-pipe-render button') ?? []
      )

    const openPipeline = async (): Promise<void> => {
      tab('流水线')?.click()
      await flush()
    }

    it('only asks the host once that page is opened', async () => {
      const bridge = installBridge({
        request: host({ 'projects/list': listing([projectRow()]) })
      })
      setupDom()
      new Function(script)()
      await openPanel()

      expect(view(PIPELINE_VIEW_ID).style.display).toBe('none')
      expect(asks(bridge, 'pipeline/plan'), '没打开这一页就别去问它跑到哪儿了').toHaveLength(0)

      await openPipeline()

      expect(view(CHAT_VIEW_ID).style.display).toBe('none')
      expect(view(PIPELINE_VIEW_ID).style.display).toBe('flex')
      expect(tab('流水线')?.dataset.active).toBe('true')
      // 下拉里是宿主 projects/list 那几行（哪个目录算一部戏是宿主判的），默认挑第一部。
      expect((view(PIPELINE_PROJECT_ID) as HTMLSelectElement).value).toBe('长夜')
      // 剧目与集数是这一页的下拉给的；原文留空就不带 —— 宿主那边缺省是它自己的默认。
      expect(bridge.request).toHaveBeenCalledWith('pipeline/plan', { name: '长夜', episodes: 12 })
    })

    it('paints the stage list exactly as the host reported it', async () => {
      installBridge({
        request: host({ 'projects/list': listing([projectRow()]), 'pipeline/plan': plan() })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openPipeline()

      expect(cards().map((one) => one.dataset.code)).toEqual(['S0', 'S1', 'S2'])
      // 谁做、落点、要不要回引擎侧渲染，全照 plan 那几栏写 —— 面板不自己判一遍。
      expect(card('S2')?.textContent).toContain('分镜智能体')
      expect(card('S2')?.textContent).toContain('落点-S2')
      expect(card('S2')?.textContent).toContain('跑完还要回引擎侧出图/视频/音频')
      expect(card('S0')?.textContent).not.toContain('跑完还要回引擎侧')
      // 「哪几段跑完还得渲染」在总览那一行也报一遍：扫一眼就够，不用一段段翻。
      expect(view(PIPELINE_OVERVIEW_ID).textContent).toContain('S2')
    })

    it('binds the stage to the workflows the host named, and runs one from the card', async () => {
      const bridge = installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'pipeline/plan': plan({
            // 项目根是绝对路径（真实载荷如此，见 pipeline.py 的 plan_payload / steps_payload）：
            // 出图时把它拼在落点前面当 output_dir，图才落得进项目。
            project: 'D:/戏/长夜',
            stages: [
              stage('S0'),
              stage('S1'),
              stage('S2', {
                needs_render: true,
                actor: '分镜智能体',
                render_targets: ['character-sheet', 'scene-card'],
                // 落点按目标分开给：角色那格与场景那格不是一个目录（见 STAGE_RENDER）。
                render_lands: { 'character-sheet': '02_CHARACTERS', 'scene-card': '05_ENVIRONMENTS' },
                render_note: '角色/服装/道具走定妆板，场景走设定卡'
              })
            ]
          }),
          'renders/list': renders([
            renderTarget(),
            renderTarget({ id: 'scene-card', title: '场景设定卡', file: '02_场景卡.json' })
          ]),
          'renders/run': () => new Promise(() => {})
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openPipeline()

      // 用哪张图是宿主 STAGE_RENDER 绑的：面板不自己挑、也不去猜（认错图不报错，只会出成另一张）。
      expect(renderButtons('S2').map((b) => b.textContent)).toEqual([
        '去出图（角色定妆板（Qwen-Image 2512））',
        '去出图（场景设定卡）'
      ])
      // 附言跟着按钮一起画：光看 id 会把话说满（哪一半用它、到哪儿为止都在这一句里）。
      expect(card('S2')?.textContent).toContain('角色/服装/道具走定妆板，场景走设定卡')
      // "跑完存哪"按之前就该看得见，而且是**按目标分开**的：两枚按钮各说自己那一格。
      expect(renderButtons('S2')[0]?.title).toContain('D:/戏/长夜/02_CHARACTERS')
      expect(renderButtons('S2')[1]?.title).toContain('D:/戏/长夜/05_ENVIRONMENTS')
      // 一格装不下（S2 就是两种落点）就不顺口说"出完存进" —— 那句话会漏掉另一半。
      expect(card('S2')?.textContent).not.toContain('出完存进')
      // 不用出图的那几段一个按钮都没有 —— 摆出来只会让人以为这一步也得回引擎侧出图。
      expect(card('S0')?.querySelector('.cs-pipe-render')).toBeNull()

      renderButtons('S2')[1]?.click()
      await flush()

      // 按下去 = 把渲染那一行切到这张图（下拉真换过去了），再走用户自己按「跑一遍」那条路。
      expect((document.getElementById(RENDER_ID) as HTMLSelectElement).value).toBe('scene-card')
      expect(view(CHAT_VIEW_ID).style.display, '跑渲染那张卡片在对话页，切过去才看得见').toBe('flex')
      expect(asks(bridge, 'renders/run')[0]?.[1]).toMatchObject({
        target_id: 'scene-card',
        // 落点拼上项目根交给渲染：图才会落进这一段体检真看的目录，卡片上「还缺图」当场就消。
        output_dir: 'D:/戏/长夜/05_ENVIRONMENTS'
      })
    })

    it('says the bound workflow is missing instead of drawing a dead button', async () => {
      installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'pipeline/plan': plan({
            stages: [
              stage('S0'),
              stage('S1'),
              stage('S2', {
                needs_render: true,
                render_targets: ['character-sheet', 'scene-card'],
                render_lands: { 'character-sheet': '02_CHARACTERS', 'scene-card': '05_ENVIRONMENTS' }
              })
            ]
          }),
          // 引擎那份清单里只有一张：另一张（改名了、或者这一版没有）不能画成能按的按钮。
          // 宿主核对不了引擎的清单（两边分开装，见 pipeline.py 的 STAGE_RENDER），这里是兜底。
          'renders/list': renders([renderTarget()])
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openPipeline()

      expect(renderButtons('S2').map((b) => b.textContent)).toEqual([
        '去出图（角色定妆板（Qwen-Image 2512））'
      ])
      const text = card('S2')?.textContent ?? ''
      expect(text).toContain('引擎那份清单里没有：scene-card')
      expect(text, '说清为什么少一枚，而不是留一行空的').toContain('引擎没起来，或者图改名了')
    })

    it('says where the shots land when the stage has one landing for all of them', async () => {
      const bridge = installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'pipeline/plan': plan({
            project: 'D:/戏/长夜',
            stages: [
              stage('S0'),
              stage('S1'),
              stage('S5', {
                needs_render: true,
                render_targets: ['video-draft', 'video-final'],
                render_lands: { 'video-draft': '09_SHOTS', 'video-final': '09_SHOTS' },
                render_note: '先试片（768p）看提示词对不对，再上正片'
              })
            ]
          }),
          'renders/list': renders([
            renderTarget({ id: 'video-draft', title: '视频 768p 试片', file: '05_试片.json', tags: ['video'] }),
            renderTarget({ id: 'video-final', title: '视频 1080p 正片', file: '06_正片.json', tags: ['video'] })
          ]),
          'renders/run': () => new Promise(() => {})
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openPipeline()

      // 几张图落同一格时顺口说一句：这一段的体检只看 09_SHOTS 而已。
      expect(card('S5')?.textContent).toContain('出完存进 09_SHOTS')

      renderButtons('S5')[0]?.click()
      await flush()

      expect(asks(bridge, 'renders/run')[0]?.[1]).toMatchObject({
        target_id: 'video-draft',
        output_dir: 'D:/戏/长夜/09_SHOTS'
      })
    })

    it('does not guess an output dir when the project path is not absolute', async () => {
      const bridge = installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          // 项目根是相对的：拼出来会相对于**引擎那边的当前目录**，图就落进一个谁也没打算的
          // 地方，而且不报错 —— 与"落点绑错"是同一种错法。
          'pipeline/plan': plan({
            project: '长夜',
            stages: [
              stage('S0'),
              stage('S1'),
              stage('S2', {
                needs_render: true,
                render_targets: ['character-sheet'],
                render_lands: { 'character-sheet': '02_CHARACTERS' }
              })
            ]
          }),
          'renders/list': renders([renderTarget()]),
          'renders/run': () => new Promise(() => {})
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openPipeline()

      expect(renderButtons('S2')[0]?.title).not.toContain('另存进')

      renderButtons('S2')[0]?.click()
      await flush()

      // 宁可让它落引擎自己的 output/：送进一个拼歪的目录更糟，而且没人会知道。
      expect(asks(bridge, 'renders/run')[0]?.[1]).not.toHaveProperty('output_dir')
    })

    it('marks the stages the host recorded as settled', async () => {
      installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'pipeline/plan': plan({
            state: { S0: { status: 'done', artifact: '落点-S0', at: 62 } }
          })
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openPipeline()

      expect(card('S0')?.dataset.status).toBe('done')
      expect(card('S0')?.textContent).toContain('跑过了')
      expect(card('S1')?.dataset.status).toBe('todo')
      expect(card('S1')?.textContent).toContain('还没跑')
      expect(view(PIPELINE_OVERVIEW_ID).textContent).toContain('跑过了 1/3 段')
    })

    it('asks before running: how many stages, how many will be skipped', async () => {
      installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'pipeline/plan': plan({ state: { S0: { status: 'done', artifact: '落点-S0', at: 62 } } })
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openPipeline()

      barButton('开跑…')?.click()
      await flush()

      expect(view(PIPELINE_FORM_ID).dataset.open).toBe('1')
      const words = view(PIPELINE_FORM_TEXT_ID).textContent ?? ''
      expect(words).toContain('共 3 段')
      expect(words).toContain('算跑过的是 S0')
      expect(words).toContain('1 段得回引擎侧出图/视频')
      // 起止两个下拉的选项就是这一趟的段，默认从头跑到尾（与宿主 run 的缺省一致）。
      expect((view(PIPELINE_FROM_ID) as HTMLSelectElement).value).toBe('S0')
      expect((view(PIPELINE_TO_ID) as HTMLSelectElement).value).toBe('S2')
    })

    it('sends the run with the stages the person picked', async () => {
      const bridge = installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'pipeline/plan': plan(),
          'pipeline/run': () => new Promise(() => {})
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openPipeline()

      barButton('开跑…')?.click()
      await flush()
      const to = view(PIPELINE_TO_ID) as HTMLSelectElement
      const force = view(PIPELINE_FORCE_ID) as HTMLInputElement
      to.value = 'S1'
      force.checked = true
      formButton('继续跑')?.click()
      await flush()

      expect(view(PIPELINE_FORM_ID).dataset.open).toBe('0')
      expect(bridge.request).toHaveBeenCalledWith('pipeline/run', {
        name: '长夜',
        episodes: 12,
        from: 'S0',
        to: 'S1',
        force: true
      })
      // 跑起来的时候那几颗按钮按下去了：不按，人会以为"再点一下能催它快一点"。
      expect(barButton('开跑…')?.disabled).toBe(true)
    })

    it('lights each stage up from the events the host pushes', async () => {
      const bridge = installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'pipeline/plan': plan(),
          'pipeline/run': () => new Promise(() => {})
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openPipeline()
      barButton('开跑…')?.click()
      await flush()
      formButton('继续跑')?.click()
      await flush()

      emit({ params: { type: 'pipeline', phase: 'start', project: '长夜', stages: ['S0', 'S1'] } })
      emit({ params: { type: 'pipeline', phase: 'stage_start', code: 'S0', actor: '剧本智能体' } })
      await flush()

      expect(card('S0')?.dataset.status).toBe('running')
      expect(hint().textContent).toContain('正在跑 S0')

      emit({ params: { type: 'pipeline', phase: 'stage', code: 'S0', status: 'done' } })
      await flush()

      expect(card('S0')?.dataset.status).toBe('done')
      expect(card('S0')?.textContent).toContain('跑过了')
      expect(card('S1')?.dataset.status).toBe('todo')

      // 跑完之后那趟回话才到：这时候按钮得放开，而且计划要重问一遍
      // —— "现在跑到哪儿了"唯一的事实源是宿主那份进度账，不是这一趟的快照。
      expect(bridge.request).toHaveBeenCalledWith('pipeline/run', {
        name: '长夜',
        episodes: 12,
        from: 'S0',
        to: 'S2'
      })
    })

    it('ignores pipeline events when nothing is running here', async () => {
      installBridge({
        request: host({ 'projects/list': listing([projectRow()]), 'pipeline/plan': plan() })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openPipeline()
      const before = card('S0')?.dataset.status

      // stage / stage_start 那两条**不带项目名**，没法核对是哪部戏；拿"这一页跑着没有"当门。
      // 不设这道门，隔壁窗口跑起来的进度会画到这一页上。
      emit({ params: { type: 'pipeline', phase: 'stage_start', code: 'S0', actor: '剧本智能体' } })
      await flush()

      expect(card('S0')?.dataset.status).toBe(before)
    })

    it('says why it cannot plan instead of painting an empty table', async () => {
      installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'pipeline/plan': { ok: false, error: { code: 'no_project', message: '没有「长夜」' } }
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openPipeline()

      expect(hint().getAttribute('data-tone')).toBe('error')
      expect(hint().textContent).toContain('没有「长夜」')
      expect(cards()).toHaveLength(0)
    })
  })

  describe('键盘', () => {
    const view = (id: string): HTMLElement => document.getElementById(id) as HTMLElement
    const tabOf = (name: string): HTMLButtonElement =>
      document.querySelector<HTMLButtonElement>(
        `#${TABS_ID} .cs-tab[data-view="${name}"]`
      ) as HTMLButtonElement
    /** 往 document 上按一个键（面板的快捷键就挂在 document 上），返回那个事件好查有没有被拦下。 */
    const press = (init: KeyboardEventInit): KeyboardEvent => {
      const event = new KeyboardEvent('keydown', { ...init, bubbles: true, cancelable: true })
      document.dispatchEvent(event)
      return event
    }
    const stub: RequestStub = (method) =>
      method === 'novels/list'
        ? { ok: true, result: { novels: [] } }
        : { ok: true, result: { text: '答案在此' } }

    it('focuses this page search box on Ctrl/Cmd+F', async () => {
      installBridge({ request: stub })
      setupDom()
      new Function(script)()
      await openPanel()

      press({ key: 'f', ctrlKey: true })
      expect(document.activeElement, '对话页就是消息区上头那个检索框').toBe(
        document.getElementById(FIND_ID)
      )

      tabOf('project').click()
      await flush()
      press({ key: 'f', metaKey: true }) // mac 上是 Cmd+F
      expect(document.activeElement, '项目页是筛项目那个框').toBe(
        document.getElementById(PROJECT_FIND_ID)
      )
    })

    it('leaves the browser find alone while the drawer is shut', async () => {
      installBridge({ request: stub })
      setupDom()
      new Function(script)()

      const event = press({ key: 'f', ctrlKey: true })

      // 面板没开就不许抢键：把键抢了又不给东西，比不抢还烦人。
      expect(event.defaultPrevented).toBe(false)
    })

    it('closes the drawer on Escape, but not while a box has the focus', async () => {
      installBridge({ request: stub })
      setupDom()
      new Function(script)()
      await openPanel()

      const input = document.getElementById(INPUT_ID) as HTMLTextAreaElement
      input.focus()
      press({ key: 'Escape' })
      // 在输入框里按 Esc 是"我还要接着改"，不是"把面板关了"。
      expect(view(DRAWER_ID).style.display).not.toBe('none')

      input.blur()
      press({ key: 'Escape' })
      expect(view(DRAWER_ID).style.display).toBe('none')
    })

    it('lays the two browsing pages over the whole window, not inside the drawer slot', async () => {
      installBridge({ request: stub })
      setupDom()
      new Function(script)()
      await openPanel()

      const layer = document.getElementById(VIEWS_ID) as HTMLElement
      // 挂在抽屉**里面**：面板那几百条样式全收在抽屉那条选择器底下，挂到 body 上就得再写一遍。
      // 铺满窗口靠的是 fixed（抽屉自己没有 transform 这类会造"包含块"的东西）。
      expect(layer.parentElement?.id).toBe(DRAWER_ID)
      expect(layer.dataset.open, '对话页不铺这一层').toBe('0')

      tabOf('novel').click()
      await flush()
      expect(layer.dataset.open).toBe('1')
      expect(
        document.getElementById(VIEWS_TITLE_ID)?.textContent,
        '铺满窗口时抽屉顶上那排标签也被盖住了 —— 得有一处说清这是哪一页'
      ).toBe('管理小说')

      document.getElementById(VIEWS_BACK_ID)?.click()
      await flush()
      expect(layer.dataset.open).toBe('0')
      expect(view(CHAT_VIEW_ID).style.display).toBe('flex')
      // 收起来只是收起来：读到哪一页、筛词是什么都还在（切回对话不是"关掉重开"）。
      expect(view(NOVEL_VIEW_ID).style.display).toBe('none')
    })

    it('takes one layer at a time on Escape, and lets a replaced instance go', async () => {
      installBridge({ request: stub })
      setupDom()
      new Function(script)()
      await openPanel()
      // 宿主刷新网页：旧的 DOM 整片没了，脚本又注入了一份新的。上一份实例还挂在 document
      // 的按键监听上 —— 它要是照着 id 摸到**新的**那面抽屉，同一个 Esc 会被新旧两只手各收
      // 一层（顺序还不一定），最后收掉什么就成了运气。
      const replaced = Reflect.get(window, '__comfyStudioChat') as
        | { drawer?: { isConnected: boolean } }
        | undefined
      expect(replaced?.drawer?.isConnected, '先确认它本来是有抽屉的').toBe(true)
      document.body.innerHTML = ''
      Reflect.deleteProperty(window, '__comfyStudioChat')
      setupDom()
      new Function(script)()
      await openPanel()
      expect(replaced?.drawer?.isConnected, '旧实例那面抽屉确实已经不在页面上了').toBe(false)

      tabOf('project').click()
      await flush()
      const layer = document.getElementById(VIEWS_ID) as HTMLElement
      expect(layer.dataset.open).toBe('1')

      // 焦点先离开输入框：在框里按 Esc 是"我还要接着改"，这条规矩对占了窗口那两页一样成立
      // （项目页那个筛词框自己就吃 Esc —— 清掉筛词，不是把这一页收了）。
      ;(document.activeElement as HTMLElement | null)?.blur()
      press({ key: 'Escape' })
      await flush()
      // 一次只收一层：按一下把"我正看的那一页"和整个面板一起收走的话，人得从头找回来。
      expect(layer.dataset.open).toBe('0')
      expect(view(CHAT_VIEW_ID).style.display).toBe('flex')
      expect(view(DRAWER_ID).style.display, '不该被上一份实例顺手关掉').not.toBe('none')

      press({ key: 'Escape' })
      await flush()
      expect(view(DRAWER_ID).style.display).toBe('none')
    })

    it('walks the tabs with the arrow keys and Home/End', async () => {
      installBridge({ request: stub })
      setupDom()
      new Function(script)()
      await openPanel()

      const chatTab = tabOf('chat')
      chatTab.focus()
      chatTab.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true })
      )
      await flush()

      const novelTab = tabOf('novel')
      expect(view(NOVEL_VIEW_ID).style.display).toBe('flex')
      expect(document.activeElement, '焦点得跟着走，否则后面按左右键都不从这儿算').toBe(novelTab)
      expect(novelTab.getAttribute('aria-selected')).toBe('true')
      expect(chatTab.getAttribute('aria-selected')).toBe('false')
      expect(chatTab.tabIndex, '只有当前这一页能被 Tab 到').toBe(-1)
      expect(novelTab.tabIndex).toBe(0)

      novelTab.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'End', bubbles: true, cancelable: true })
      )
      await flush()
      // End 落到最后一页：现在是「流水线」（它排在项目管理后面）
      expect(view(PIPELINE_VIEW_ID).style.display).toBe('flex')
      expect(document.activeElement).toBe(tabOf('pipeline'))

      // 到头了绕回第一页 —— 现在排在最前的是「工作台」（它是这条链的入口）
      tabOf('pipeline').dispatchEvent(
        new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true })
      )
      await flush()
      expect(view(WORKBENCH_VIEW_ID).style.display).toBe('flex')
      expect(document.activeElement).toBe(tabOf('workbench'))
    })

    it('says which page each tab stands for', async () => {
      installBridge({ request: stub })
      setupDom()
      new Function(script)()
      await openPanel()

      // 读屏软件靠这几个属性才说得清"这是个标签、它管哪一块、现在选的是哪个"。
      expect(document.getElementById(TABS_ID)?.getAttribute('role')).toBe('tablist')
      expect(tabOf('chat').getAttribute('role')).toBe('tab')
      expect(tabOf('chat').getAttribute('aria-controls')).toBe(CHAT_VIEW_ID)
      expect(tabOf('project').getAttribute('aria-controls')).toBe(PROJECT_VIEW_ID)
      expect(tabOf('pipeline').getAttribute('aria-controls')).toBe(PIPELINE_VIEW_ID)
      expect(tabOf('chat').getAttribute('aria-selected')).toBe('true')
      expect(view(CHAT_VIEW_ID).getAttribute('role')).toBe('tabpanel')
      expect(view(PROJECT_VIEW_ID).getAttribute('role')).toBe('tabpanel')
      expect(view(PIPELINE_VIEW_ID).getAttribute('role')).toBe('tabpanel')
    })
  })

  describe('工作台', () => {
    /** 宿主 projects/list 里的一行。这一页只借它填剧目下拉。 */
    const projectRow = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
      name: '长夜',
      path: 'D:/comfy/custom_nodes/comfy_studio/manju/projects/长夜',
      files: 3,
      missing: [],
      missing_count: 0,
      stages: [],
      stages_done: 1,
      stages_total: 1,
      mtime: 1758900000,
      ...over
    })

    const listing = (projects: unknown[]): unknown => ({
      ok: true,
      result: {
        dir: 'D:/comfy/custom_nodes/comfy_studio/manju/projects',
        exists: true,
        query: '',
        matched: projects.length,
        returned: projects.length,
        truncated: false,
        limit: 200,
        projects
      }
    })

    /**
     * pipeline/steps 里的一步。栏名**照宿主 steps_payload 抄** —— 面板画的就是那几栏，
     * 名字对不上就成了一条永远空着的行。key 与先后也全照宿主的来：这一页不自己编号、
     * 不自己排一次序，否则"面板说还差第三步、模型说早跑完了"，两边都不报错。
     */
    const stepOf = (
      key: string,
      name: string,
      over: Record<string, unknown> = {}
    ): Record<string, unknown> => ({
      key,
      name,
      goal: '',
      note: '',
      needs: [],
      stages: [],
      landings: [],
      count: 0,
      seed_count: 0,
      state: 'empty',
      blocked_by: [],
      ready: true,
      ...over
    })

    /** 一步认领的一个落点格子。 */
    const landingOf = (
      rel: string,
      over: Record<string, unknown> = {}
    ): Record<string, unknown> => ({
      rel,
      title: rel,
      shelf: '',
      scope: '',
      exists: true,
      files: [],
      count: 0,
      seed_count: 0,
      truncated: false,
      ...over
    })

    const fileOf = (rel: string, over: Record<string, unknown> = {}): Record<string, unknown> => ({
      rel,
      name: rel.split('/').pop() ?? rel,
      bytes: 12,
      mtime: 1758900000,
      readable: true,
      seed: false,
      ...over
    })

    /** 一步底下的机器阶段（谁做、落哪、要不要回引擎侧渲染，全由这几栏说了算）。 */
    const stageOf = (
      code: string,
      over: Record<string, unknown> = {}
    ): Record<string, unknown> => ({
      code,
      name: code + ' 那一段',
      owner: 'script',
      agent: 'studio-script',
      actor: '剧本智能体',
      artifact: '落点-' + code,
      needs_render: false,
      state: 'todo',
      agent_name: '剧本智能体',
      how: '跑 ' + code,
      ...over
    })

    const payloadOf = (over: Record<string, unknown> = {}): unknown => ({
      ok: true,
      result: {
        project: 'D:/comfy/custom_nodes/comfy_studio/manju/projects/长夜',
        name: '长夜',
        novel: '长夜.txt',
        linked_novel: '',
        gaps: [],
        order: [],
        current: '',
        steps: [],
        render_required: [],
        ...over
      }
    })

    /** 只有工作台那几件事走自己的桩；开抽屉时要问的那些保持默认。 */
    const host =
      (handlers: Record<string, unknown>): RequestStub =>
      (method, params) =>
        method in handlers
          ? typeof handlers[method] === 'function'
            ? (handlers[method] as RequestStub)(method, params)
            : handlers[method]
          : { ok: true, result: { text: '答案在此' } }

    const view = (id: string): HTMLElement => document.getElementById(id) as HTMLElement
    const tab = (label: string): HTMLButtonElement | undefined =>
      Array.from(document.querySelectorAll<HTMLButtonElement>(`#${TABS_ID} .cs-tab`)).find(
        (b) => b.textContent === label
      )
    const tile = (key: string): HTMLElement | null =>
      document.querySelector<HTMLElement>(`#${WORKBENCH_STEPS_ID} .cs-wb-step[data-step="${key}"]`)
    const tiles = (): HTMLElement[] =>
      Array.from(document.querySelectorAll<HTMLElement>(`#${WORKBENCH_STEPS_ID} .cs-wb-step`))
    const fileRow = (rel: string): HTMLButtonElement | null =>
      document.querySelector<HTMLButtonElement>(
        `#${WORKBENCH_DETAIL_ID} .cs-wb-file[data-rel="${rel}"]`
      )
    const edit = (): HTMLTextAreaElement => view(WORKBENCH_EDIT_ID) as HTMLTextAreaElement
    const save = (): HTMLButtonElement => view(WORKBENCH_SAVE_ID) as HTMLButtonElement
    const saveHint = (): HTMLElement => view(WORKBENCH_SAVE_HINT_ID)
    const hint = (): HTMLElement => view(WORKBENCH_HINT_ID)
    const detail = (): HTMLElement => view(WORKBENCH_DETAIL_ID)
    const asks = (bridge: StudioBridge, method: string): unknown[][] =>
      bridge.request.mock.calls.filter((call: unknown[]) => call[0] === method)

    const openWorkbench = async (): Promise<void> => {
      tab('工作台')?.click()
      await flush()
    }

    /** 读一份落点里的资料，并把宿主那一段回话交回给调用处核对。 */
    const readFile = async (rel: string): Promise<void> => {
      fileRow(rel)?.click()
      await flush()
    }

    /** 一套三步的读数：第一步做完了、第二步还没动、第三步只出了文本。 */
    const threeSteps = (): Record<string, unknown>[] => [
      stepOf('parse', '小说文本解析', {
        state: 'done',
        count: 3,
        stages: [stageOf('S0a', { state: 'done' })],
        landings: [
          landingOf('00_PROJECT/00_原文解析', {
            count: 3,
            files: [fileOf('00_PROJECT/00_原文解析/人物表.md')]
          })
        ]
      }),
      stepOf('cast', '角色与场景提取', {
        state: 'empty',
        needs: ['parse'],
        blocked_by: ['parse']
      }),
      stepOf('board', '分镜脚本', {
        state: 'partial',
        count: 1,
        stages: [stageOf('S4', { state: 'text' })],
        landings: [
          landingOf('08_STORYBOARDS', {
            count: 1,
            files: [fileOf('08_STORYBOARDS/EP01.md', { bytes: 2048 })]
          })
        ]
      })
    ]

    it('only asks the host once that page is opened', async () => {
      const bridge = installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'pipeline/steps': payloadOf({ order: ['parse'], current: 'parse', steps: threeSteps() })
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()

      expect(view(WORKBENCH_VIEW_ID).style.display).toBe('none')
      expect(asks(bridge, 'pipeline/steps'), '没打开这一页就别去问它走到第几步了').toHaveLength(0)

      await openWorkbench()

      expect(view(CHAT_VIEW_ID).style.display).toBe('none')
      expect(view(WORKBENCH_VIEW_ID).style.display).toBe('flex')
      expect(tab('工作台')?.dataset.active).toBe('true')
      // 下拉里是宿主 projects/list 那几行，默认挑第一部。
      expect((view(WORKBENCH_PROJECT_ID) as HTMLSelectElement).value).toBe('长夜')
      expect(bridge.request).toHaveBeenCalledWith('pipeline/steps', { name: '长夜' })
    })

    it('paints the steps exactly as the host reported them', async () => {
      installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'pipeline/steps': payloadOf({
            order: ['parse', 'cast', 'board'],
            current: 'cast',
            steps: threeSteps()
          })
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openWorkbench()

      // 顺序照宿主 order，名字照宿主 name，数照宿主 count，状态照宿主 state —— 一条都不自己算。
      expect(tiles().map((one) => one.dataset.step)).toEqual(['parse', 'cast', 'board'])
      expect(tiles().map((one) => one.querySelector('.cs-wb-step-name')?.textContent)).toEqual([
        '小说文本解析',
        '角色与场景提取',
        '分镜脚本'
      ])
      expect(tiles().map((one) => one.querySelector('.cs-wb-step-count')?.textContent)).toEqual([
        '3',
        '0',
        '1'
      ])
      expect(tiles().map((one) => one.dataset.state)).toEqual(['done', 'empty', 'partial'])
      expect(tile('parse')?.textContent).toContain('成了')
      expect(tile('cast')?.textContent).toContain('还没动')
      // 「现在该看哪一步」是宿主说的 current，不是第一个没做完的、也不是面板自己数的。
      expect(tile('cast')?.dataset.current).toBe('1')
      expect(tile('parse')?.dataset.current).toBeUndefined()
      // 一格一个序号：人靠它说"第几步"，所以宁可照 order 的下标，也不按数组位置编。
      expect(tiles().map((one) => one.querySelector('.cs-wb-step-no')?.textContent)).toEqual([
        '1',
        '2',
        '3'
      ])
    })

    it('adds up the eight steps from the same reading, and says what is missing', async () => {
      installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'pipeline/steps': payloadOf({
            order: ['parse', 'cast', 'board'],
            current: 'cast',
            gaps: ['阶段 S9 不在工作台任何一步里'],
            steps: [
              stepOf('parse', '小说文本解析', { state: 'done', seed_count: 2 }),
              stepOf('cast', '角色与场景提取', { state: 'empty' }),
              stepOf('board', '分镜脚本', {
                state: 'partial',
                stages: [stageOf('S4', { state: 'missing' })]
              })
            ]
          })
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openWorkbench()

      const line = view(WORKBENCH_OVERVIEW_ID).textContent ?? ''
      expect(line).toContain('八步走了 1/3 步')
      expect(line).toContain('现在该看：角色与场景提取')
      expect(line).toContain('有 1 段的产物不见了')
      expect(line).toContain('另有 2 份预置空表（不算进度）')
      expect(line).toContain('原文：长夜.txt')
      // gaps 非空是宿主那张步骤表自己的毛病：不说出来，它就只是"少了一步"，没有别的迹象。
      expect(line).toContain('步骤表对不上（1 处）')
    })

    it('reads a file whole and writes it back with the digest it read', async () => {
      const text = '第一镜：雪落长街。'
      const bridge = installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'pipeline/steps': payloadOf({
            order: ['board'],
            current: 'board',
            steps: [
              stepOf('board', '分镜脚本', {
                state: 'partial',
                stages: [stageOf('S4', { state: 'done' })],
                landings: [
                  landingOf('08_STORYBOARDS', {
                    count: 1,
                    files: [fileOf('08_STORYBOARDS/EP01.md')]
                  })
                ]
              })
            ]
          }),
          'projects/read': {
            ok: true,
            result: {
              name: '长夜',
              rel: '08_STORYBOARDS/EP01.md',
              encoding: 'utf-8',
              bytes: 24,
              digest: 'd1',
              total_chars: text.length,
              offset: 0,
              chars: text.length,
              truncated: false,
              text
            }
          },
          'projects/write': {
            ok: true,
            result: {
              name: '长夜',
              rel: '08_STORYBOARDS/EP01.md',
              bytes: 30,
              chars: 10,
              created: false,
              digest: 'd2'
            }
          }
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openWorkbench()
      await readFile('08_STORYBOARDS/EP01.md')

      // **整份读**：这一栏的目的就是改完写回去，只读一页的话，写回时会把没读到的那半截删掉。
      expect(bridge.request).toHaveBeenCalledWith('projects/read', {
        name: '长夜',
        rel: '08_STORYBOARDS/EP01.md',
        whole: true
      })
      expect(edit().value).toBe(text)
      expect(edit().readOnly).toBe(false)

      edit().value = '第一镜：雪落长街，灯一盏。'
      edit().dispatchEvent(new Event('input'))
      save().click()
      await flush()

      // 带的是**读进来那一刻**的摘要：宿主拿它核对"我改的是我读到的这一版"。
      expect(bridge.request).toHaveBeenCalledWith('projects/write', {
        name: '长夜',
        rel: '08_STORYBOARDS/EP01.md',
        text: '第一镜：雪落长街，灯一盏。',
        base_digest: 'd1'
      })
      expect(saveHint().textContent).toBe('写好了。')
      // 写回之后落点里那份的"多新"变了：重问一遍宿主，但正在编辑的这一栏留着。
      expect(asks(bridge, 'pipeline/steps')).toHaveLength(2)
      expect(edit().value).toBe('第一镜：雪落长街，灯一盏。')
    })

    it('says why the host refused the write instead of overwriting', async () => {
      const bridge = installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'pipeline/steps': payloadOf({
            order: ['board'],
            current: 'board',
            steps: [
              stepOf('board', '分镜脚本', {
                state: 'partial',
                landings: [
                  landingOf('08_STORYBOARDS', {
                    count: 1,
                    files: [fileOf('08_STORYBOARDS/EP01.md')]
                  })
                ]
              })
            ]
          }),
          'projects/read': {
            ok: true,
            result: {
              name: '长夜',
              rel: '08_STORYBOARDS/EP01.md',
              encoding: 'utf-8',
              digest: 'd1',
              total_chars: 4,
              offset: 0,
              chars: 4,
              truncated: false,
              text: '第一镜'
            }
          },
          'projects/write': {
            ok: false,
            error: { code: 'conflict', message: '在编辑期间被改过了，请重读一遍' }
          }
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openWorkbench()
      await readFile('08_STORYBOARDS/EP01.md')

      edit().value = '第二镜'
      edit().dispatchEvent(new Event('input'))
      save().click()
      await flush()

      // 被拒不是失败，是"你手上这份已经不是最新的"：把宿主那句话说出来，
      // **不**自作主张地覆盖，也不把人刚打的字清掉。
      expect(saveHint().textContent).toContain('没写成')
      expect(saveHint().textContent).toContain('在编辑期间被改过了')
      expect(saveHint().getAttribute('data-tone')).toBe('error')
      expect(hint().textContent).toContain('08_STORYBOARDS/EP01.md')
      expect(edit().value).toBe('第二镜')
      expect(asks(bridge, 'projects/write')).toHaveLength(1)
    })

    it('only shows a too-long file, and never writes half of it back', async () => {
      const bridge = installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'pipeline/steps': payloadOf({
            order: ['board'],
            current: 'board',
            steps: [
              stepOf('board', '分镜脚本', {
                state: 'partial',
                landings: [
                  landingOf('08_STORYBOARDS', {
                    count: 1,
                    files: [fileOf('08_STORYBOARDS/EP01.md')]
                  })
                ]
              })
            ]
          }),
          'projects/read': {
            ok: true,
            result: {
              name: '长夜',
              rel: '08_STORYBOARDS/EP01.md',
              encoding: 'utf-8',
              digest: 'd1',
              total_chars: 900000,
              offset: 0,
              chars: 200000,
              truncated: true,
              text: '前面这一段'
            }
          }
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openWorkbench()
      await readFile('08_STORYBOARDS/EP01.md')

      // 半份也"合法"（那是一段更短的完整文本），所以这道拦必须在**这一侧**：
      // truncated 为真就只给看，保存键直接按下去。
      expect(edit().readOnly).toBe(true)
      expect(save().disabled).toBe(true)
      expect(save().title).toContain('不拿半份写回去')
      expect(detail().textContent).toContain('只读')
      expect(detail().textContent).toContain('面板不拿半份写回去')

      // 保存键按下去也不该发出一个写请求：disabled 只是一层皮，真正的拦在这一侧。
      save().click()
      await flush()
      expect(asks(bridge, 'projects/write')).toHaveLength(0)
    })

    it('asks before dropping unsaved edits when another file is picked', async () => {
      const bridge = installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'pipeline/steps': payloadOf({
            order: ['board'],
            current: 'board',
            steps: [
              stepOf('board', '分镜脚本', {
                state: 'partial',
                landings: [
                  landingOf('08_STORYBOARDS', {
                    count: 2,
                    files: [fileOf('08_STORYBOARDS/EP01.md'), fileOf('08_STORYBOARDS/EP02.md')]
                  })
                ]
              })
            ]
          }),
          'projects/read': {
            ok: true,
            result: {
              name: '长夜',
              rel: '08_STORYBOARDS/EP01.md',
              encoding: 'utf-8',
              digest: 'd1',
              total_chars: 4,
              offset: 0,
              chars: 4,
              truncated: false,
              text: '第一镜'
            }
          }
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openWorkbench()
      await readFile('08_STORYBOARDS/EP01.md')

      edit().value = '改到一半'
      edit().dispatchEvent(new Event('input'))
      await readFile('08_STORYBOARDS/EP02.md')

      // 丢字这种事**不会报错**：人只会过一会儿发现刚才写的没了，从此不再信这个编辑框。
      expect(hint().textContent).toContain('改过还没保存')
      expect(asks(bridge, 'projects/read')).toHaveLength(1)
      expect(edit().value).toBe('改到一半')
    })

    it('drops the file it was holding when another step is picked', async () => {
      installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'pipeline/steps': payloadOf({
            order: ['board', 'cut'],
            current: 'board',
            steps: [
              stepOf('board', '分镜脚本', {
                state: 'partial',
                landings: [
                  landingOf('08_STORYBOARDS', {
                    count: 1,
                    files: [fileOf('08_STORYBOARDS/EP01.md')]
                  })
                ]
              }),
              stepOf('cut', '短剧合成', { state: 'empty' })
            ]
          }),
          'projects/read': {
            ok: true,
            result: {
              name: '长夜',
              rel: '08_STORYBOARDS/EP01.md',
              encoding: 'utf-8',
              digest: 'd1',
              total_chars: 4,
              offset: 0,
              chars: 4,
              truncated: false,
              text: '第一镜'
            }
          }
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openWorkbench()
      await readFile('08_STORYBOARDS/EP01.md')
      expect(view(WORKBENCH_EDIT_ID)).not.toBeNull()

      tile('cut')?.click()
      await flush()

      // 换了一步，手上那份就不是这一步的了：留着的话编辑框里是上一步的正文，
      // 按下保存会写到**另一个**文件上去（名字对不上，宿主的乐观锁也拦不住）。
      expect(detail().textContent).toContain('短剧合成')
      expect(document.getElementById(WORKBENCH_EDIT_ID)).toBeNull()
      expect(view(WORKBENCH_READER_ID).textContent).toContain('点上面任何一份资料')
    })

    it('says the upstream it is still waiting on, by name', async () => {
      installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'pipeline/steps': payloadOf({
            order: ['parse', 'board'],
            current: 'board',
            steps: [
              stepOf('parse', '小说文本解析', { state: 'empty' }),
              stepOf('board', '分镜脚本', {
                state: 'empty',
                needs: ['parse'],
                blocked_by: ['parse'],
                stages: [stageOf('S4', { state: 'todo' })]
              })
            ]
          })
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openWorkbench()
      tile('board')?.click()
      await flush()

      // blocked_by 里存的是 key，把 key 原样摆上去（"还等：parse"）等于让人去猜。
      expect(detail().textContent).toContain('还等：小说文本解析')
      // 这一步的阶段卡照宿主那几栏念：谁做、落哪、怎么跑。
      expect(detail().textContent).toContain('S4')
    })

    it('hands the conversation over to the agent this stage uses', async () => {
      const bridge = installBridge({
        request: host({
          'projects/list': listing([projectRow()]),
          'pipeline/steps': payloadOf({
            order: ['board'],
            current: 'board',
            steps: [
              stepOf('board', '分镜脚本', {
                state: 'empty',
                stages: [stageOf('S4', { state: 'todo' })]
              })
            ]
          }),
          'agent/agent': {
            ok: true,
            result: { agent: 'studio-storyboard', name: '分镜导演' }
          }
        })
      })
      setupDom()
      new Function(script)()
      await openPanel()
      await openWorkbench()

      const button = Array.from(
        document.querySelectorAll<HTMLButtonElement>(`#${WORKBENCH_DETAIL_ID} .cs-proj-btn`)
      ).find((one) => one.textContent === '用「剧本智能体」')
      button?.click()
      await flush()

      expect(bridge.request).toHaveBeenCalledWith('agent/agent', { agent: 'studio-script' })
      // 换完就切回对话页：留人在这页看着一个已经变了的"人设"，下一步点哪儿都是猜。
      expect(view(CHAT_VIEW_ID).style.display).toBe('flex')
      expect(view(WORKBENCH_VIEW_ID).style.display).toBe('none')
    })
  })
})
