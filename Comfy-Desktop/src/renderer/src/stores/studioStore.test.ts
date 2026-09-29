import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type {
  ComfyStudioEventMessage,
  ComfyStudioRequestResult,
  ComfyStudioStatus
} from '../../../types/comfyDesktopBridge'
import { useStudioStore } from './studioStore'

/** Captured `onStudioEvent` callback — tests push host notifications through it
 *  the way the real host does (one app-wide channel, every window sees them). */
let emit: ((message: ComfyStudioEventMessage) => void) | null = null

const runningStatus: ComfyStudioStatus = {
  installationId: 'inst-1',
  available: true,
  running: true
}

const stoppedStatus: ComfyStudioStatus = {
  installationId: 'inst-1',
  available: true,
  running: false
}

function installApi(overrides: Record<string, unknown> = {}): void {
  const api = {
    studioStatus: vi.fn(async () => stoppedStatus),
    studioStart: vi.fn(async () => runningStatus),
    studioStop: vi.fn(async () => stoppedStatus),
    studioRequest: vi.fn(async (): Promise<ComfyStudioRequestResult> => ({ ok: true, result: null })),
    onStudioEvent: vi.fn((callback: (message: ComfyStudioEventMessage) => void) => {
      emit = callback
      return () => {
        emit = null
      }
    }),
    getSetting: vi.fn(async () => 'injected'),
    setSetting: vi.fn(async () => undefined),
    ...overrides
  }
  Object.defineProperty(window, 'api', { value: api, configurable: true, writable: true })
}

function message(params: Record<string, unknown>): ComfyStudioEventMessage {
  return { installationId: 'inst-1', method: 'agent/event', params }
}

beforeEach(() => {
  setActivePinia(createPinia())
  emit = null
  installApi()
})

describe('studioStore', () => {
  it('reads host status and the surface preference on init', async () => {
    const store = useStudioStore()
    expect(store.hostState).toBe('unknown')

    await store.init('inst-1')

    expect(store.hostState).toBe('stopped')
    expect(store.activeSection).toBe('drama')
    expect(store.surface).toBe('injected')
    expect(emit).not.toBeNull()
  })

  it('treats an install that cannot host as unavailable, not stopped', async () => {
    installApi({
      studioStatus: vi.fn(async () => ({ ...stoppedStatus, available: false, error: 'no venv' }))
    })
    const store = useStudioStore()

    await store.init('inst-1')

    expect(store.hostState).toBe('unavailable')
  })

  it('filters the app-wide event channel down to this install', async () => {
    const store = useStudioStore()
    await store.init('inst-1')

    emit?.(message({ type: 'op_preview', opId: 'a' }))
    emit?.({ installationId: 'other', method: 'agent/event', params: { type: 'op_preview' } })

    expect(store.events).toHaveLength(2)
    expect(store.visibleEvents).toHaveLength(1)
  })

  it('follows a host view hint while the user has not pinned a section', async () => {
    const store = useStudioStore()
    await store.init('inst-1')

    emit?.(message({ type: 'view', section: 'assets' }))

    expect(store.activeSection).toBe('assets')
    expect(store.pendingSuggestion).toBeNull()
  })

  it('degrades a host view hint to a suggestion once the user pins', async () => {
    const store = useStudioStore()
    await store.init('inst-1')
    store.togglePin()

    emit?.(message({ type: 'view', section: 'assets' }))

    // Pin wins: the panel does not move under the user.
    expect(store.activeSection).toBe('drama')
    expect(store.pendingSuggestion).toBe('assets')
    expect(store.isPinned).toBe(true)
  })

  it('ignores view hints that name no known section', async () => {
    const store = useStudioStore()
    await store.init('inst-1')

    emit?.(message({ type: 'view', section: 'workbench' }))

    expect(store.activeSection).toBe('drama')
    expect(store.pendingSuggestion).toBeNull()
  })

  it('persists the surface flip instead of only holding it in memory', async () => {
    const store = useStudioStore()
    await store.init('inst-1')

    await store.setSurface('native')

    expect(store.surface).toBe('native')
    expect(window.api.setSetting).toHaveBeenCalledWith('studioSurface', 'native')
  })

  it('surfaces a failed host call as store state rather than throwing', async () => {
    installApi({
      studioRequest: vi.fn(
        async (): Promise<ComfyStudioRequestResult> => ({
          ok: false,
          error: { message: 'unknown method' }
        })
      )
    })
    const store = useStudioStore()
    await store.init('inst-1')

    await store.request('nope/nope')

    expect(store.error).toBe('unknown method')
  })

  it('stops listening on dispose so a closed panel keeps no store alive', async () => {
    const store = useStudioStore()
    await store.init('inst-1')

    store.dispose()

    expect(emit).toBeNull()
  })
})
