import { beforeEach, describe, expect, it, vi } from 'vitest'

type IpcHandler = (event: { sender: object }, ...args: unknown[]) => unknown

const mocks = vi.hoisted(() => ({
  handlers: new Map<string, IpcHandler>(),
  get: vi.fn(),
  findInstallationIdByComfySender: vi.fn(),
  getEntryByInstallationId: vi.fn(),
  broadcast: vi.fn(),
  hosts: [] as Array<{ startCount: number; running: boolean; stopCount: number }>
}))

vi.mock('electron', () => ({
  app: { on: vi.fn() },
  ipcMain: {
    handle: vi.fn((channel: string, handler: IpcHandler) => {
      mocks.handlers.set(channel, handler)
    })
  }
}))

vi.mock('../../installations', () => ({ get: mocks.get }))

vi.mock('../../host/registry', () => ({
  findInstallationIdByComfySender: mocks.findInstallationIdByComfySender,
  getEntryByInstallationId: mocks.getEntryByInstallationId
}))

vi.mock('../comfyStudioCanvasRelay', () => ({
  isCanvasCall: vi.fn(() => false),
  relayCanvasCall: vi.fn()
}))

vi.mock('./broadcast', () => ({ _broadcastToRenderer: mocks.broadcast }))

vi.mock('../comfyStudioHost', () => {
  class ComfyStudioHost {
    startCount = 0
    stopCount = 0
    running = false
    readonly comfyuiDir = 'ComfyUI'

    constructor() {
      mocks.hosts.push(this)
    }

    start(): void {
      this.startCount += 1
      this.running = true
    }

    stop(): void {
      this.stopCount += 1
      this.running = false
    }

    on(): this {
      return this
    }

    request(): Promise<unknown> {
      return Promise.resolve(null)
    }
  }

  class ComfyStudioError extends Error {}

  return {
    ComfyStudioHost,
    ComfyStudioError,
    resolveStudioCommand: () => ({
      cmd: 'python',
      args: [],
      cwd: 'lib',
      comfyuiDir: 'ComfyUI'
    })
  }
})

/** `hosts` / `hostsStarting` 都是模块级状态，所以每个用例都取一份干净的模块。 */
async function loadHandlers(): Promise<Map<string, IpcHandler>> {
  vi.resetModules()
  mocks.handlers.clear()
  mocks.hosts.length = 0
  const module = await import('./registerComfyStudioHandlers')
  module.registerComfyStudioHandlers()
  return mocks.handlers
}

function handler(handlers: Map<string, IpcHandler>, channel: string): IpcHandler {
  const found = handlers.get(channel)
  expect(found).toBeDefined()
  return found!
}

/** `installations.get` 卡住不返回：这正是原来漏进程的那个窗口。 */
function holdInstallationsLookup(): () => void {
  let release: (installation: unknown) => void = () => {}
  mocks.get.mockImplementation(
    () =>
      new Promise((resolve) => {
        release = resolve
      })
  )
  return () => release({ installPath: 'ComfyUI-Install' })
}

describe('registerComfyStudioHandlers', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.findInstallationIdByComfySender.mockReturnValue('inst-a')
    mocks.get.mockResolvedValue({ installPath: 'ComfyUI-Install' })
  })

  // 面板打开会同时发好几个请求，而建宿主要先 await installations.get：没有在途
  // 去重的话每个调用都看见空 Map，于是各起一个进程（实测一次 8 个，41ms 内）。
  it('hands concurrent requests one host instead of one each', async () => {
    const handlers = await loadHandlers()
    const release = holdInstallationsLookup()

    const request = handler(handlers, 'comfy-studio:request')
    const calls = Array.from({ length: 6 }, () =>
      request({ sender: {} }, { method: 'agent/models', params: {} })
    )
    await Promise.resolve()
    release()
    await Promise.all(calls)

    expect(mocks.get).toHaveBeenCalledTimes(1)
    expect(mocks.hosts).toHaveLength(1)
  })

  it('hands concurrent starts one host instead of one each', async () => {
    const handlers = await loadHandlers()
    const release = holdInstallationsLookup()

    const start = handler(handlers, 'comfy-studio:start')
    const calls = Array.from({ length: 8 }, () => start({ sender: {} }, null))
    await Promise.resolve()
    release()
    await Promise.all(calls)

    expect(mocks.hosts).toHaveLength(1)
    // 8 个调用都落在同一个实例上；重复 start() 只是幂等空转，不是第二个进程。
    expect(mocks.hosts[0].startCount).toBe(8)
  })

  it('reuses the host once it exists', async () => {
    const handlers = await loadHandlers()
    const start = handler(handlers, 'comfy-studio:start')

    await start({ sender: {} }, null)
    await start({ sender: {} }, null)

    expect(mocks.hosts).toHaveLength(1)
    expect(mocks.get).toHaveBeenCalledTimes(1)
  })

  // 失败的那次创建不能把 key 永久占住，否则这个安装从此再也起不来。
  it('retries after a failed creation', async () => {
    const handlers = await loadHandlers()
    mocks.get.mockResolvedValueOnce(null)
    const start = handler(handlers, 'comfy-studio:start')

    const first = (await start({ sender: {} }, null)) as { available: boolean }
    expect(first.available).toBe(false)
    expect(mocks.hosts).toHaveLength(0)

    const second = (await start({ sender: {} }, null)) as { available: boolean }
    expect(second.available).toBe(true)
    expect(mocks.hosts).toHaveLength(1)
  })
})
