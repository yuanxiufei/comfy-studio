<script setup lang="ts">
/**
 * Always-visible status band of the studio surface.
 *
 * Why a band and not a footer: the studio drives long host jobs (pipeline runs,
 * renders) that can outlive the section the user is looking at, so host state,
 * the running job and the surface switch have to stay in one fixed place. The
 * rail and the panel below it both scroll; this does not.
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { CircleAlert, Play, RefreshCw, Square, X } from 'lucide-vue-next'
import { useStudioStore } from '../stores/studioStore'

const emit = defineEmits<{
  close: []
}>()

const { t } = useI18n()
const studio = useStudioStore()

const hostLabel = computed(() => t(`studio.host.${studio.hostState}`))
const surfaceLabel = computed(() => t(`studio.surface.${studio.surface}`))
const canStart = computed(
  () => studio.hostState === 'stopped' || studio.hostState === 'unavailable'
)
const canStop = computed(() => studio.hostState === 'running')
</script>

<template>
  <header class="studio-band">
    <div class="studio-band__identity">
      <span class="studio-band__title">{{ t('studio.title') }}</span>
      <span class="studio-band__state" :data-state="studio.hostState">
        {{ hostLabel }}
      </span>
      <span v-if="studio.status?.comfyuiDir" class="studio-band__path" :title="studio.status.comfyuiDir">
        {{ studio.status.comfyuiDir }}
      </span>
    </div>

    <div class="studio-band__actions">
      <span v-if="studio.error" class="studio-band__error" :title="studio.error">
        <CircleAlert :size="14" />
        {{ studio.error }}
      </span>
      <button
        type="button"
        class="studio-band__surface"
        :title="t('studio.surface.hint')"
        @click="studio.setSurface(studio.surface === 'native' ? 'injected' : 'native')"
      >
        {{ t('studio.surface.label') }}: {{ surfaceLabel }}
      </button>
      <button
        type="button"
        class="studio-band__icon"
        :title="t('studio.host.start')"
        :disabled="!canStart || studio.busy"
        @click="studio.startHost()"
      >
        <Play :size="14" />
      </button>
      <button
        type="button"
        class="studio-band__icon"
        :title="t('studio.host.stop')"
        :disabled="!canStop || studio.busy"
        @click="studio.stopHost()"
      >
        <Square :size="14" />
      </button>
      <button
        type="button"
        class="studio-band__icon"
        :title="t('studio.host.refresh')"
        :disabled="studio.busy"
        @click="studio.refreshStatus()"
      >
        <RefreshCw :size="14" :class="{ 'is-spinning': studio.busy }" />
      </button>
      <button
        type="button"
        class="studio-band__icon"
        :title="t('studio.close')"
        @click="emit('close')"
      >
        <X :size="14" />
      </button>
    </div>
  </header>
</template>

<style scoped>
.studio-band {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  height: 36px;
  padding: 0 12px;
  background: var(--studio-band-bg);
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  color: var(--text);
  user-select: none;
}

.studio-band__identity,
.studio-band__actions {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.studio-band__title {
  font-weight: 600;
}

.studio-band__state {
  padding: 1px 6px;
  border-radius: 999px;
  border: 1px solid var(--border);
  color: var(--text-muted);
}

.studio-band__state[data-state='running'] {
  border-color: var(--success);
  color: var(--success);
}

.studio-band__state[data-state='unavailable'] {
  border-color: var(--warning);
  color: var(--warning);
}

.studio-band__path {
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-faint);
}

.studio-band__error {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--danger);
}

.studio-band__surface,
.studio-band__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 24px;
  padding: 0 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
  cursor: pointer;
}

.studio-band__icon {
  padding: 0 6px;
}

.studio-band__surface:hover,
.studio-band__icon:hover:not(:disabled) {
  border-color: var(--border-hover);
  color: var(--text);
}

.studio-band__icon:disabled {
  opacity: 0.4;
  cursor: default;
}

.studio-band__icon:focus-visible,
.studio-band__surface:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}

.is-spinning {
  animation: studio-spin 900ms linear infinite;
}

@keyframes studio-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .is-spinning {
    animation: none;
  }
}
</style>
