<script setup lang="ts">
/**
 * The model server's address, model name and key — the three settings that
 * decide whether the picker above has anything in it.
 *
 * Where the drawer had no equivalent, this panel's hard part is *not* being
 * pre-filled wrongly, and the host's answer shape makes that a real trap:
 *
 * - `agent/settings` on a **read** puts the file's contents in `saved`; on a
 *   **write** it overwrites that same key with the boolean `true`. So the form
 *   never reads `saved` after saving — `prefillSettings` prefers the effective
 *   `model` / `base_url`, which both verbs carry.
 * - The key is never returned, only `has_key`. An empty key field therefore has
 *   to mean "leave the stored key alone", or every save would wipe it; deleting
 *   it takes the explicit button.
 * - `from_env` lists the keys the environment supplies on its own. Those
 *   override the file, so editing them here changes nothing — which the panel
 *   says out loud instead of letting a user save and wonder.
 */
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlertCircle, CircleCheck, LoaderCircle, Save } from 'lucide-vue-next'
import { useAgentSetupStore } from '../stores/agentSetupStore'
import { savedSettings } from './pages/agentSetup'

const emit = defineEmits<{ close: [] }>()

const setup = useAgentSetupStore()
const { t, n } = useI18n()

const model = ref(setup.formSeed.model)
const baseUrl = ref(setup.formSeed.baseUrl)
const apiKey = ref('')
const clearKey = ref(false)

// Re-seed whenever a fresh payload lands (the panel can be opened before the
// first read finishes, and a save re-reads `model` / `base_url`).
watch(
  () => setup.formSeed,
  (seed) => {
    if (setup.saving) return
    model.value = seed.model
    baseUrl.value = seed.baseUrl
  }
)

watch(clearKey, (on) => {
  if (on) apiKey.value = ''
})

async function save(): Promise<void> {
  const ok = await setup.saveSettings({
    model: model.value,
    baseUrl: baseUrl.value,
    apiKey: apiKey.value,
    clearKey: clearKey.value
  })
  if (ok) {
    apiKey.value = ''
    clearKey.value = false
  }
}
</script>

<template>
  <section class="model">
    <header class="model__head">
      <span class="model__title">{{ t('studio.model.title') }}</span>
      <span v-if="setup.settings?.configured" class="model__ok">
        <CircleCheck :size="11" />
        <span>{{ t('studio.model.configured') }}</span>
      </span>
      <span class="model__spacer" />
      <button type="button" class="model__close" @click="emit('close')">
        {{ t('studio.model.close') }}
      </button>
    </header>

    <p v-if="setup.settingsError" class="model__error">
      <AlertCircle :size="11" />
      <span>{{ setup.settingsError }}</span>
    </p>

    <template v-else>
      <p v-if="setup.settings && !setup.settings.path" class="model__hint">
        {{ t('studio.model.noStore') }}
      </p>

      <p v-if="setup.settings?.error" class="model__error">
        <AlertCircle :size="11" />
        <span>{{ t('studio.model.notDone') }} · {{ setup.settings.error }}</span>
      </p>
      <p v-if="setup.settings?.file_error" class="model__error">
        <AlertCircle :size="11" />
        <span>{{ t('studio.model.fileError') }} · {{ setup.settings.file_error }}</span>
      </p>
      <p v-if="(setup.settings?.from_env.length ?? 0) > 0" class="model__warn">
        {{ t('studio.model.fromEnv', { keys: setup.settings?.from_env.join(' · ') }) }}
      </p>

      <label class="model__field">
        <span class="model__label">{{ t('studio.model.model') }}</span>
        <input v-model="model" class="model__input" type="text" spellcheck="false" />
      </label>

      <label class="model__field">
        <span class="model__label">{{ t('studio.model.baseUrl') }}</span>
        <input v-model="baseUrl" class="model__input" type="text" spellcheck="false" />
      </label>

      <label class="model__field">
        <span class="model__label">
          {{ t('studio.model.apiKey') }}
          <span v-if="savedSettings(setup.settings)?.has_key" class="model__has">
            {{ t('studio.model.hasKey') }}
          </span>
        </span>
        <input
          v-model="apiKey"
          class="model__input"
          type="password"
          autocomplete="off"
          :disabled="clearKey"
          :placeholder="t('studio.model.apiKeyHint')"
        />
      </label>

      <label class="model__check">
        <input v-model="clearKey" type="checkbox" />
        <span>{{ t('studio.model.clearKey') }}</span>
      </label>

      <p v-if="savedSettings(setup.settings)?.extra_sources.length" class="model__hint">
        {{
          t('studio.model.extraSources', {
            count: n(savedSettings(setup.settings)?.extra_sources.length ?? 0)
          })
        }}
        ·
        {{ savedSettings(setup.settings)?.extra_sources.map((row) => row.name).join(' · ') }}
      </p>

      <p v-if="setup.applied.length > 0" class="model__hint">
        {{ t('studio.model.applied', { count: n(setup.applied.length) }) }}
      </p>
      <p v-if="setup.skipped.length > 0" class="model__warn">
        {{ t('studio.model.skipped', { count: n(setup.skipped.length) }) }}
      </p>

      <div class="model__actions">
        <button type="button" class="model__save" :disabled="setup.saving" @click="save()">
          <LoaderCircle v-if="setup.saving" :size="12" class="is-spinning" />
          <Save v-else :size="12" />
          <span>{{ setup.saving ? t('studio.model.saving') : t('studio.model.save') }}</span>
        </button>
        <p v-if="setup.settings?.path" class="model__path">{{ setup.settings.path }}</p>
      </div>
    </template>
  </section>
</template>

<style scoped>
.model {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-top: 6px;
  padding: 8px;
  border: 1px solid var(--studio-card-border);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.02);
}

.model__head {
  display: flex;
  align-items: center;
  gap: 6px;
}

.model__title {
  color: var(--text);
  font-size: 11px;
}

.model__ok {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  color: var(--success, var(--accent));
  font-size: 10px;
}

.model__spacer {
  flex: 1;
}

.model__close {
  padding: 2px 6px;
  border: 1px solid transparent;
  border-radius: 5px;
  background: transparent;
  color: var(--text-faint);
  font: inherit;
  font-size: 10px;
  cursor: pointer;
}

.model__close:hover {
  color: var(--text);
  border-color: var(--studio-card-border);
}

.model__field {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.model__label {
  display: flex;
  align-items: baseline;
  gap: 5px;
  color: var(--text-muted);
  font-size: 10px;
}

.model__has {
  color: var(--text-faint);
}

.model__input {
  padding: 4px 6px;
  border: 1px solid var(--studio-card-border);
  border-radius: 5px;
  background: var(--studio-input-bg, rgba(0, 0, 0, 0.2));
  color: var(--text);
  font: inherit;
  font-size: 11px;
}

.model__input:focus {
  outline: none;
  border-color: var(--accent);
}

.model__input:disabled {
  opacity: 0.5;
}

.model__check {
  display: flex;
  align-items: center;
  gap: 5px;
  color: var(--text-muted);
  font-size: 10px;
  cursor: pointer;
}

.model__hint,
.model__warn,
.model__error {
  display: flex;
  align-items: flex-start;
  gap: 4px;
  margin: 0;
  font-size: 10px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.model__hint {
  color: var(--text-faint);
}

.model__warn {
  color: var(--warning);
}

.model__error {
  color: var(--danger);
}

.model__actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.model__save {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border: 1px solid var(--studio-card-border);
  border-radius: 5px;
  background: var(--studio-card-bg);
  color: var(--text-muted);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}

.model__save:hover:not(:disabled) {
  color: var(--text);
  border-color: var(--accent);
}

.model__save:disabled {
  opacity: 0.45;
  cursor: default;
}

.model__path {
  flex: 1;
  min-width: 0;
  margin: 0;
  color: var(--text-faint);
  font-family: 'Cascadia Mono', 'Consolas', monospace;
  font-size: 9px;
  overflow-wrap: anywhere;
}

.is-spinning {
  animation: model-spin 900ms linear infinite;
}

@keyframes model-spin {
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
