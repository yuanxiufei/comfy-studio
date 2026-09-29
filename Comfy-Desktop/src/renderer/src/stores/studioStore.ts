import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type {
  ComfyStudioEventMessage,
  ComfyStudioRequestResult,
  ComfyStudioStatus
} from '../../../types/comfyDesktopBridge'
import { DEFAULT_SECTION, isStudioSectionId, type StudioSectionId } from '../studio/sections'

/** Ring-buffer cap for the host event log. The rail shows a live tail; keeping
 *  unbounded history in the renderer would grow without bound on long renders. */
const MAX_EVENTS = 200

/** Host surface state as the shell cares about it. Four states, not two: a
 *  window whose install can't host at all must read differently from one the
 *  user simply hasn't started yet. */
export type StudioHostState = 'unknown' | 'unavailable' | 'stopped' | 'running'

export type StudioSurface = 'native' | 'injected'

/**
 * State of the native studio surface.
 *
 * One store (not per-component state) because the status band, the rail and the
 * section nav all read the same host: the band shows `hostState`, the rail wants
 * the event tail, and the nav needs to keep the user's pin when a host-driven
 * `view` hint arrives.
 */
export const useStudioStore = defineStore('studio', () => {
  /** Set from the panel URL (see `PanelApp.vue`). A panelView sender is not a
   *  comfyView sender, so main cannot infer the install — every call carries it. */
  const installationId = ref('')
  const status = ref<ComfyStudioStatus | null>(null)
  const busy = ref(false)
  const error = ref<string | null>(null)
  const events = ref<ComfyStudioEventMessage[]>([])
  const activeSection = ref<StudioSectionId>(DEFAULT_SECTION)
  /** `null` = follow the host, otherwise the user has pinned a section and
   *  host-driven switches degrade to a suggestion instead of stealing focus. */
  const pinnedSection = ref<StudioSectionId | null>(null)
  const pendingSuggestion = ref<StudioSectionId | null>(null)
  const surface = ref<StudioSurface>('injected')

  let unsubscribe: (() => void) | null = null

  const hostState = computed<StudioHostState>(() => {
    const current = status.value
    if (!current) return 'unknown'
    if (!current.available) return 'unavailable'
    return current.running ? 'running' : 'stopped'
  })

  const isPinned = computed(() => pinnedSection.value === activeSection.value)

  /** Events are app-wide (one IPC channel for every Comfy window), so filter to
   *  ours. Without the filter a second window's chat turn would show up here. */
  const visibleEvents = computed(() =>
    installationId.value
      ? events.value.filter((event) => event.installationId === installationId.value)
      : events.value
  )

  function consume(result: ComfyStudioRequestResult): void {
    if (!result.ok) error.value = result.error.message
  }

  async function refreshStatus(): Promise<void> {
    if (!installationId.value) return
    busy.value = true
    try {
      status.value = await window.api.studioStatus(installationId.value)
      error.value = null
    } catch (caught) {
      // Host unavailable is a normal state (broken checkout, python missing) —
      // surface it in the band rather than throwing into the console.
      error.value = caught instanceof Error ? caught.message : String(caught)
      status.value = null
    } finally {
      busy.value = false
    }
  }

  async function startHost(): Promise<void> {
    if (!installationId.value) return
    busy.value = true
    try {
      status.value = await window.api.studioStart(installationId.value)
      error.value = null
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : String(caught)
    } finally {
      busy.value = false
    }
  }

  async function stopHost(): Promise<void> {
    if (!installationId.value) return
    busy.value = true
    try {
      status.value = await window.api.studioStop(installationId.value)
      error.value = null
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : String(caught)
    } finally {
      busy.value = false
    }
  }

  /** Host call proxy. Used by the pages landing in later milestones; already
   *  exercised by the shell (status/refresh) so the bridge is proven end to end. */
  async function request(
    method: string,
    params: Record<string, unknown> = {}
  ): Promise<ComfyStudioRequestResult> {
    const result = await window.api.studioRequest(method, params, installationId.value)
    consume(result)
    return result
  }

  function subscribe(): void {
    if (unsubscribe) return
    unsubscribe = window.api.onStudioEvent((message) => {
      events.value = [...events.value, message].slice(-MAX_EVENTS)
      applyViewHint(message)
    })
  }

  /** Host-driven section switch (`agent/event {type:'view'}` from a tool call).
   *  Never applied over an explicit pin — that is the difference between an
   *  assistant moving the furniture and one yanking it away. */
  function applyViewHint(message: ComfyStudioEventMessage): void {
    const params = message.params as { type?: string; section?: unknown } | undefined
    if (!params || params.type !== 'view') return
    if (!isStudioSectionId(params.section)) return
    if (pinnedSection.value) {
      pendingSuggestion.value = params.section
      return
    }
    activeSection.value = params.section
  }

  function setSection(section: StudioSectionId): void {
    activeSection.value = section
    pendingSuggestion.value = null
  }

  function togglePin(): void {
    pinnedSection.value = pinnedSection.value === activeSection.value ? null : activeSection.value
    if (pinnedSection.value) pendingSuggestion.value = null
  }

  function clearEvents(): void {
    events.value = []
  }

  async function init(id: string): Promise<void> {
    if (installationId.value !== id) {
      installationId.value = id
      status.value = null
      events.value = []
    }
    subscribe()
    const stored = await window.api.getSetting('studioSurface')
    surface.value = stored === 'native' ? 'native' : 'injected'
    await refreshStatus()
  }

  /** Flip which surface renders Studio. Legacy drawer ↔ native panel: the point
   *  of the setting is that neither surface is ever removed by the other. */
  async function setSurface(next: StudioSurface): Promise<void> {
    surface.value = next
    await window.api.setSetting('studioSurface', next)
  }

  function dispose(): void {
    unsubscribe?.()
    unsubscribe = null
  }

  return {
    installationId,
    status,
    busy,
    error,
    events,
    activeSection,
    pinnedSection,
    pendingSuggestion,
    surface,
    hostState,
    isPinned,
    visibleEvents,
    init,
    refreshStatus,
    startHost,
    stopHost,
    request,
    setSection,
    togglePin,
    clearEvents,
    setSurface,
    dispose
  }
})
