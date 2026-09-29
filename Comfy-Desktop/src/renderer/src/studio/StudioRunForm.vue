<script setup lang="ts">
/**
 * The "跑一次" form: one control per declared parameter, plus the render-only
 * extras (reference images, duration, output directory).
 *
 * Controls are chosen by the parameter's declared *type*, and nothing is
 * validated beyond what the host will actually reject. That line matters: the
 * engine has its own defaults and its own required-set, so a form that guessed
 * at them would block requests the engine would have accepted. So a blank field
 * is simply omitted (the engine applies its default), and the only two local
 * refusals are the ones that would otherwise come back as a protocol error:
 * a required parameter with no default, and a non-numeric number.
 *
 * The form owns the text; the parent owns the run. `submit` hands over typed
 * values, and the parent decides which endpoint they belong to.
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlertCircle, Play, X } from 'lucide-vue-next'
import { paramKind, collectParams, parseDuration, prefillParams } from './pages/runs'
import type { SkillParam } from './pages/capabilities'

const props = defineProps<{
  params: readonly SkillParam[]
  /** A run is already in flight for this row. */
  busy: boolean
  /** Renders only: the reference-image, duration and output-directory fields. */
  withMedia?: boolean
  /** Only show the image field when the target actually declares reference
   *  images — otherwise it invites a path the workflow will ignore. */
  referenceImages?: boolean
}>()

const emit = defineEmits<{
  submit: [
    payload: { params: Record<string, unknown>; images: string; durationSec: string; outputDir: string }
  ]
  cancel: []
}>()

const { t } = useI18n()

const values = ref<Record<string, string>>(prefillParams(props.params))
const images = ref('')
const durationSec = ref('')
const outputDir = ref('')

/** Which complaints to show. Kept as flags rather than a message so that the
 *  wording stays in the locale files, and so editing a field clears its own
 *  warning without disturbing the others. */
const missing = ref<string[]>([])
const invalid = ref<string[]>([])
const badDuration = ref(false)

const kinds = computed(() =>
  props.params.map((param) => ({ param, kind: paramKind(param.type) }))
)

/** The default, shown as a placeholder hint. `hasDefault` on a null default is
 *  a real answer — "the engine's default is null" — so it says so. */
function hintFor(param: SkillParam): string {
  if (!param.hasDefault) return ''
  const value = param.default
  if (value === null || value === undefined) return t('studio.capabilities.run.defaultNull')
  return t('studio.capabilities.run.defaultHint', { value: String(value) })
}

function submit(): void {
  const collected = collectParams(props.params, values.value)
  missing.value = collected.missing
  invalid.value = collected.invalid

  const duration = parseDuration(durationSec.value)
  badDuration.value = !duration.ok
  if (missing.value.length > 0 || invalid.value.length > 0 || badDuration.value) return

  emit('submit', {
    params: collected.values,
    images: images.value,
    durationSec: durationSec.value,
    outputDir: outputDir.value
  })
}

/** Clear the complaint about one field the moment it is edited, so the message
 *  never outlives the problem. */
function touch(name: string): void {
  if (missing.value.includes(name)) missing.value = missing.value.filter((item) => item !== name)
  if (invalid.value.includes(name)) invalid.value = invalid.value.filter((item) => item !== name)
}

function touchDuration(): void {
  badDuration.value = false
}
</script>

<template>
  <form class="runform" @submit.prevent="submit">
    <p v-if="kinds.length === 0" class="runform__hint">
      {{ t('studio.capabilities.run.noParams') }}
    </p>

    <div v-for="entry in kinds" :key="entry.param.name" class="runform__field">
      <label class="runform__label" :for="`run-${entry.param.name}`">
        <span class="runform__name">{{ entry.param.name }}</span>
        <span v-if="entry.param.required" class="runform__required">
          {{ t('studio.capabilities.run.requiredMark') }}
        </span>
        <span v-if="hintFor(entry.param)" class="runform__default">{{ hintFor(entry.param) }}</span>
      </label>

      <select
        v-if="entry.kind === 'boolean'"
        :id="`run-${entry.param.name}`"
        v-model="values[entry.param.name]"
        class="runform__input"
        @change="touch(entry.param.name)"
      >
        <option value="">{{ t('studio.capabilities.run.boolAny') }}</option>
        <option value="true">{{ t('studio.capabilities.run.boolTrue') }}</option>
        <option value="false">{{ t('studio.capabilities.run.boolFalse') }}</option>
      </select>

      <input
        v-else
        :id="`run-${entry.param.name}`"
        v-model="values[entry.param.name]"
        class="runform__input"
        type="text"
        :inputmode="entry.kind === 'number' ? 'decimal' : 'text'"
        :placeholder="hintFor(entry.param)"
        @input="touch(entry.param.name)"
      />

      <p v-if="entry.param.description" class="runform__desc">{{ entry.param.description }}</p>
    </div>

    <template v-if="withMedia">
      <div v-if="referenceImages" class="runform__field">
        <label class="runform__label" for="run-images">
          <span class="runform__name">{{ t('studio.capabilities.run.images') }}</span>
        </label>
        <textarea
          id="run-images"
          v-model="images"
          class="runform__input runform__input--area"
          rows="2"
          spellcheck="false"
        />
        <p class="runform__desc">{{ t('studio.capabilities.run.imagesHint') }}</p>
      </div>

      <div class="runform__field">
        <label class="runform__label" for="run-duration">
          <span class="runform__name">{{ t('studio.capabilities.run.duration') }}</span>
        </label>
        <input
          id="run-duration"
          v-model="durationSec"
          class="runform__input"
          type="text"
          inputmode="decimal"
          @input="touchDuration"
        />
        <p v-if="badDuration" class="runform__error">
          <AlertCircle :size="11" />
          <span>{{ t('studio.capabilities.run.badDuration') }}</span>
        </p>
      </div>

      <div class="runform__field">
        <label class="runform__label" for="run-output">
          <span class="runform__name">{{ t('studio.capabilities.run.outputDir') }}</span>
        </label>
        <input id="run-output" v-model="outputDir" class="runform__input" type="text" />
      </div>
    </template>

    <p v-if="missing.length > 0" class="runform__error">
      <AlertCircle :size="11" />
      <span>{{ t('studio.capabilities.run.missing', { names: missing.join(' · ') }) }}</span>
    </p>
    <p v-if="invalid.length > 0" class="runform__error">
      <AlertCircle :size="11" />
      <span>{{ t('studio.capabilities.run.invalid', { names: invalid.join(' · ') }) }}</span>
    </p>

    <div class="runform__actions">
      <button type="submit" class="runform__go" :disabled="busy">
        <Play :size="12" />
        <span>{{
          busy ? t('studio.capabilities.run.running') : t('studio.capabilities.run.submit')
        }}</span>
      </button>
      <button type="button" class="runform__cancel" :disabled="busy" @click="emit('cancel')">
        <X :size="12" />
        <span>{{ t('studio.capabilities.run.cancel') }}</span>
      </button>
    </div>
  </form>
</template>

<style scoped>
.runform {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 6px;
  padding: 8px;
  border: 1px solid var(--studio-card-border);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.02);
}

.runform__field {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.runform__label {
  display: flex;
  align-items: baseline;
  gap: 5px;
}

.runform__name {
  color: var(--text);
  font-size: 11px;
  font-family: 'Cascadia Mono', 'Consolas', monospace;
}

.runform__required {
  flex: none;
  color: var(--warning);
  font-size: 10px;
}

.runform__default {
  flex: 1;
  min-width: 0;
  color: var(--text-faint);
  font-size: 10px;
  overflow-wrap: anywhere;
}

.runform__input {
  padding: 4px 6px;
  border: 1px solid var(--studio-card-border);
  border-radius: 5px;
  background: var(--studio-input-bg, rgba(0, 0, 0, 0.2));
  color: var(--text);
  font: inherit;
  font-size: 11px;
}

.runform__input--area {
  resize: vertical;
  font-family: 'Cascadia Mono', 'Consolas', monospace;
  font-size: 10px;
}

.runform__input:focus {
  outline: none;
  border-color: var(--accent);
}

.runform__desc,
.runform__hint {
  margin: 0;
  color: var(--text-faint);
  font-size: 10px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.runform__error {
  display: flex;
  align-items: flex-start;
  gap: 4px;
  margin: 0;
  color: var(--danger);
  font-size: 11px;
  line-height: 1.5;
}

.runform__actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.runform__go,
.runform__cancel {
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

.runform__go:hover:not(:disabled),
.runform__cancel:hover:not(:disabled) {
  color: var(--text);
  border-color: var(--accent);
}

.runform__go:disabled,
.runform__cancel:disabled {
  opacity: 0.45;
  cursor: default;
}
</style>
