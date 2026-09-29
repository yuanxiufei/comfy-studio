<script setup lang="ts">
/**
 * Native comfy-studio (漫剧) surface — layout shell.
 *
 * Replaces the injected drawer as the studio's entry point over the ComfyUI
 * canvas. The rail (P2) is the real conversation against the same host RPCs the
 * drawer used. The drama pages (P3) are real too; the pages still waiting say
 * which milestone rebuilds them rather than pretending to be empty panels.
 *
 * Layout rationale: conversation is the spine, so the rail is fixed and the
 * panel switches per task. The rail is never replaced by a page.
 *
 * Two levels of nav, because they answer different questions: sections are what
 * kind of work this is (a show / the assets), pages are which part of it
 * (novel → project → production). One page is mounted at a time — production
 * holds a live run, and mounting it behind the others would keep it subscribed.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Pin, PinOff } from 'lucide-vue-next'
import { useConversationStore } from '../stores/conversationStore'
import { useStudioStore } from '../stores/studioStore'
import { STUDIO_SECTIONS, pagesOf } from './sections'
import StudioArtifactsPage from './pages/StudioArtifactsPage.vue'
import StudioCapabilitiesPage from './pages/StudioCapabilitiesPage.vue'
import StudioJournalPage from './pages/StudioJournalPage.vue'
import StudioNovelPage from './pages/StudioNovelPage.vue'
import StudioProductionPage from './pages/StudioProductionPage.vue'
import StudioProjectPage from './pages/StudioProjectPage.vue'
import StudioRail from './StudioRail.vue'
import StudioStatusBand from './StudioStatusBand.vue'
import type { StudioPageId } from './sections'

const props = defineProps<{
  installationId: string
}>()

const emit = defineEmits<{
  close: []
}>()

const { t } = useI18n()
const studio = useStudioStore()
const conversation = useConversationStore()

/** Rail width in px. Draggable, clamped — see `RAIL_MIN` / `RAIL_MAX`. */
const RAIL_MIN = 360
const RAIL_MAX = 560
const railWidth = ref(420)
const dragging = ref(false)

const pages = computed(() => pagesOf(studio.activeSection))

/** Pages still waiting on a component keep their milestone card. */
const pendingPages = computed(() => pages.value.filter((page) => !page.built))

const activePage = ref<StudioPageId>(pages.value[0]?.id ?? 'novel')

/** Sections have disjoint pages, so a section switch always invalidates the
 *  page; land on the section's first page rather than a page it doesn't own. */
watch(pages, (list) => {
  if (list.some((page) => page.id === activePage.value)) return
  activePage.value = list[0]?.id ?? 'novel'
})

function onRailPointerDown(event: PointerEvent): void {
  dragging.value = true
  const startX = event.clientX
  const startWidth = railWidth.value

  const move = (moveEvent: PointerEvent): void => {
    const next = startWidth + (moveEvent.clientX - startX)
    railWidth.value = Math.min(RAIL_MAX, Math.max(RAIL_MIN, next))
  }
  const stop = (): void => {
    dragging.value = false
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', stop)
  }

  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', stop)
}

/** Host-driven section switch while the user pinned another one degrades to a
 *  suggestion chip — auto-switching over an explicit pin is how you lose work. */
function acceptSuggestion(): void {
  if (studio.pendingSuggestion) studio.setSection(studio.pendingSuggestion)
}

onMounted(() => {
  void studio.init(props.installationId).then(() => {
    // The rail needs the host state before it asks for history: querying an
    // archive on a stopped host would only produce an error card up front.
    return conversation.init({
      turnCancelled: t('studio.card.cancelled'),
      turnUnlocked: t('studio.card.pending.unlocked')
    })
  })
})

onBeforeUnmount(() => {
  conversation.dispose()
  studio.dispose()
})
</script>

<template>
  <div class="studio">
    <StudioStatusBand @close="emit('close')" />

    <div class="studio__body" :class="{ 'is-dragging': dragging }">
      <aside class="studio-rail" :style="{ width: `${railWidth}px` }">
        <StudioRail />

        <div
          class="studio-rail__resize"
          role="separator"
          aria-orientation="vertical"
          :aria-label="t('studio.rail.resize')"
          @pointerdown.prevent="onRailPointerDown"
        />
      </aside>

      <section class="studio-panel">
        <div class="studio-panel__nav">
          <button
            v-for="section in STUDIO_SECTIONS"
            :key="section.id"
            type="button"
            class="studio-panel__tab"
            :class="{ 'is-active': section.id === studio.activeSection }"
            @click="studio.setSection(section.id)"
          >
            {{ t(section.labelKey) }}
          </button>
          <button
            type="button"
            class="studio-panel__pin"
            :class="{ 'is-active': studio.isPinned }"
            :title="studio.isPinned ? t('studio.unpin') : t('studio.pin')"
            @click="studio.togglePin()"
          >
            <PinOff v-if="studio.isPinned" :size="14" />
            <Pin v-else :size="14" />
          </button>
        </div>

        <button
          v-if="studio.pendingSuggestion"
          type="button"
          class="studio-panel__suggestion"
          @click="acceptSuggestion"
        >
          {{ t('studio.suggestSwitch', { section: t('studio.section.' + studio.pendingSuggestion) }) }}
        </button>

        <div v-if="pages.length > 1" class="studio-panel__pages">
          <button
            v-for="page in pages"
            :key="page.id"
            type="button"
            class="studio-panel__page"
            :class="{ 'is-active': page.id === activePage }"
            @click="activePage = page.id"
          >
            <span>{{ t(page.labelKey) }}</span>
            <span v-if="!page.built" class="studio-card__milestone">
              {{ page.milestone }}
            </span>
          </button>
        </div>

        <div class="studio-panel__body">
          <StudioNovelPage v-if="activePage === 'novel'" />
          <StudioProjectPage v-else-if="activePage === 'project'" />
          <StudioProductionPage v-else-if="activePage === 'production'" />
          <StudioArtifactsPage v-else-if="activePage === 'artifacts'" />
          <StudioCapabilitiesPage v-else-if="activePage === 'capabilities'" />
          <StudioJournalPage v-else-if="activePage === 'journal'" />

          <div v-else class="studio-panel__grid">
            <article v-for="page in pendingPages" :key="page.id" class="studio-card">
              <header class="studio-card__head">
                <span class="studio-card__title">{{ t(page.labelKey) }}</span>
                <span class="studio-card__milestone">{{ page.milestone }}</span>
              </header>
              <p class="studio-card__note">{{ t('studio.pagePending') }}</p>
            </article>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.studio {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  background: var(--studio-panel-bg);
  color: var(--text);
}

.studio__body {
  display: flex;
  flex: 1;
  min-height: 0;
}

.studio__body.is-dragging {
  cursor: col-resize;
  user-select: none;
}

.studio-rail {
  position: relative;
  display: flex;
  flex-direction: column;
  flex: none;
  min-width: 0;
  background: var(--studio-rail-bg);
  border-right: 1px solid var(--border);
}

.studio-rail__resize {
  position: absolute;
  top: 0;
  right: -3px;
  width: 6px;
  height: 100%;
  cursor: col-resize;
}

.studio-panel {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  min-height: 0;
}

.studio-panel__nav {
  display: flex;
  align-items: center;
  gap: 4px;
  height: 36px;
  padding: 0 12px;
  border-bottom: 1px solid var(--border);
}

.studio-panel__tab {
  height: 24px;
  padding: 0 10px;
  border: 1px solid transparent;
  border-radius: 999px;
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
  cursor: pointer;
}

.studio-panel__tab.is-active {
  border-color: var(--border);
  background: var(--studio-card-bg);
  color: var(--text);
}

.studio-panel__pin {
  display: inline-flex;
  align-items: center;
  margin-left: auto;
  height: 24px;
  padding: 0 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
}

.studio-panel__pin.is-active {
  border-color: var(--accent);
  color: var(--accent);
}

.studio-panel__suggestion {
  margin: 8px 12px 0;
  padding: 6px 10px;
  border: 1px dashed var(--border);
  border-radius: 8px;
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
  text-align: left;
  cursor: pointer;
}

.studio-panel__pages {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 6px 12px 0;
}

.studio-panel__page {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 24px;
  padding: 0 9px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
  cursor: pointer;
}

.studio-panel__page:hover {
  color: var(--text);
}

.studio-panel__page.is-active {
  border-color: var(--studio-card-border);
  background: var(--studio-card-bg);
  color: var(--text);
}

.studio-panel__page .studio-card__milestone {
  padding: 0 4px;
  font-size: 10px;
}

.studio-panel__body {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  padding: 12px;
}

.studio-panel__body > * {
  flex: 1;
  min-height: 0;
}

.studio-panel__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
  overflow-y: auto;
}

.studio-card {
  padding: 12px;
  border: 1px solid var(--studio-card-border);
  border-radius: 10px;
  background: var(--studio-card-bg);
}

.studio-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.studio-card__title {
  font-size: 13px;
  font-weight: 600;
}

.studio-card__milestone {
  padding: 1px 6px;
  border: 1px solid var(--border);
  border-radius: 999px;
  font-size: 11px;
  color: var(--text-faint);
}

.studio-card__note {
  margin: 8px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-faint);
}

.studio-panel__tab:focus-visible,
.studio-panel__page:focus-visible,
.studio-panel__pin:focus-visible,
.studio-panel__suggestion:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}

/* Narrow windows: the panel matters more than the rail's width, so the rail
 * collapses to its minimum before anything overlaps. */
@media (max-width: 1100px) {
  .studio-rail {
    width: 360px !important;
  }
}
</style>
