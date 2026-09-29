<script setup lang="ts">
/**
 * What a finished "跑一次" left behind.
 *
 * Two failure modes are kept visibly separate, because they are fixed in
 * different places: a *transport* error (`error`) means the request never
 * reached the engine, while `isError` is the engine's own answer — "model not
 * found", "out of VRAM" — and its `data` is half-built or absent in that case,
 * which is why nothing is read from it.
 *
 * Artefacts are rendered from `data.images` with the filename always spelled out
 * beside them. Not decoration: the file URL may point outside the panel's
 * reachable scheme, and a thumbnail that silently fails to load would otherwise
 * look like a run that produced nothing.
 */
import { useI18n } from 'vue-i18n'
import { AlertCircle, CircleCheck, TriangleAlert } from 'lucide-vue-next'
import type { RunMediaKind, RunOutcome } from './pages/runs'

const props = defineProps<{
  outcome: RunOutcome | null
  /** Transport message: the run never reached the engine. */
  error: string | null
}>()

const { t } = useI18n()

/** The engine's label, in the reader's language. Named as a function rather
 *  than a lookup table so an unknown kind still gets a word. */
function kindLabel(kind: RunMediaKind): string {
  if (kind === 'video') return t('studio.capabilities.run.video')
  if (kind === 'audio') return t('studio.capabilities.run.audio')
  if (kind === 'image') return t('studio.capabilities.run.image')
  return t('studio.capabilities.run.file')
}
</script>

<template>
  <div class="runresult">
    <p v-if="error" class="runresult__error">
      <AlertCircle :size="12" />
      <span>{{ error }}</span>
    </p>

    <template v-else-if="outcome">
      <p v-if="outcome.isError" class="runresult__error">
        <TriangleAlert :size="12" />
        <span>{{ t('studio.capabilities.run.failed') }}</span>
      </p>

      <pre v-if="outcome.text" class="runresult__text">{{ outcome.text }}</pre>

      <p v-if="outcome.isError" class="runresult__hint">
        {{ t('studio.capabilities.run.failedHint') }}
      </p>

      <template v-else>
        <ul v-if="outcome.media.length > 0" class="runresult__media">
          <li v-for="(item, index) in outcome.media" :key="`${item.url}-${index}`" class="runresult__shot">
            <img
              v-if="item.kind === 'image' && item.url"
              :src="item.url"
              :alt="item.filename"
              class="runresult__asset"
              loading="lazy"
            />
            <video
              v-else-if="item.kind === 'video' && item.url"
              :src="item.url"
              class="runresult__asset"
              controls
              preload="metadata"
            />
            <audio
              v-else-if="item.kind === 'audio' && item.url"
              :src="item.url"
              class="runresult__sound"
              controls
              preload="metadata"
            />
            <p class="runresult__file">
              <span class="runresult__kind">{{ kindLabel(item.kind) }}</span>
              <span class="runresult__path" :title="item.node">
                {{ item.subfolder ? `${item.subfolder}/${item.filename}` : item.filename || item.url }}
              </span>
            </p>
          </li>
        </ul>
        <p v-else class="runresult__hint">
          <CircleCheck :size="12" />
          <span>{{ t('studio.capabilities.run.noOutput') }}</span>
        </p>

        <p v-if="outcome.notes.length > 0" class="runresult__hint">
          {{ t('studio.capabilities.run.notes') }}
        </p>
        <ul v-if="outcome.notes.length > 0" class="runresult__notes">
          <li v-for="(note, index) in outcome.notes" :key="`note-${index}`">{{ note }}</li>
        </ul>

        <p v-if="outcome.saved.length > 0" class="runresult__hint">
          {{ t('studio.capabilities.run.saved') }}
        </p>
        <ul v-if="outcome.saved.length > 0" class="runresult__notes">
          <li v-for="(item, index) in outcome.saved" :key="`saved-${index}`" class="runresult__path">
            {{ item }}
          </li>
        </ul>
      </template>
    </template>
  </div>
</template>

<style scoped>
.runresult {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-top: 6px;
  padding: 8px;
  border: 1px solid var(--studio-card-border);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.02);
}

.runresult__error {
  display: flex;
  align-items: flex-start;
  gap: 5px;
  margin: 0;
  color: var(--danger);
  font-size: 11px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.runresult__text {
  max-height: 180px;
  margin: 0;
  padding: 6px;
  overflow: auto;
  border-radius: 5px;
  background: rgba(0, 0, 0, 0.22);
  color: var(--text-muted);
  font-family: 'Cascadia Mono', 'Consolas', monospace;
  font-size: 10px;
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.runresult__hint {
  display: flex;
  align-items: center;
  gap: 4px;
  margin: 0;
  color: var(--text-faint);
  font-size: 10px;
  line-height: 1.5;
}

.runresult__media {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.runresult__shot {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.runresult__asset {
  width: 100%;
  border: 1px solid var(--studio-card-border);
  border-radius: 5px;
  background: rgba(0, 0, 0, 0.2);
  object-fit: contain;
}

.runresult__sound {
  width: 100%;
  height: 28px;
}

.runresult__file {
  display: flex;
  align-items: baseline;
  gap: 4px;
  margin: 0;
  min-width: 0;
}

.runresult__kind {
  flex: none;
  color: var(--text-faint);
  font-size: 10px;
}

.runresult__path {
  min-width: 0;
  color: var(--text-muted);
  font-family: 'Cascadia Mono', 'Consolas', monospace;
  font-size: 10px;
  overflow-wrap: anywhere;
}

.runresult__notes {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0;
  padding-left: 14px;
  color: var(--text-muted);
  font-size: 10px;
  line-height: 1.5;
}
</style>
