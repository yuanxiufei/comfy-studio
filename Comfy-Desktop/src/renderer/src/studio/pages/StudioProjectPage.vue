<script setup lang="ts">
/**
 * Projects: what a run of the studio leaves on disk, and the few edits that
 * belong next to it.
 *
 * Two habits run through this page. First, nothing is hidden — unrecognised
 * directories, seeded templates and missing required files are all shown, each
 * labelled, because "the file isn't there" is the single most common reason a
 * later stage refuses to run. Second, an edit is only ever made on top of a file
 * the user has actually read: the host hands back a digest with the text and the
 * save quotes it back, so a stale editor is refused instead of obeyed.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  AlertCircle,
  ChevronDown,
  ChevronRight,
  FileText,
  FolderOpen,
  Info,
  LoaderCircle,
  RefreshCw,
  Save,
  Sparkles,
  Wrench,
  X
} from 'lucide-vue-next'
import { useConversationStore } from '../../stores/conversationStore'
import { useProjectsStore } from '../../stores/projectsStore'
import { actionTallies, splitSeeds, type LandingBucket } from './projects'
import { formatBytes } from './novels'

const projects = useProjectsStore()
const conversation = useConversationStore()
const { t, n } = useI18n()

const showCreate = ref(false)
const showLink = ref(false)
const briefFlash = ref('')
const expanded = ref<Record<string, boolean>>({})
let flashTimer: ReturnType<typeof setTimeout> | null = null

const tallies = computed(() => (projects.dryRun ? actionTallies(projects.dryRun.counts) : []))
const migrateApplied = computed(() => projects.dryRun !== null && !projects.dryRun.dry)

onMounted(() => {
  if (!projects.loadedShelf) void projects.refresh()
})

onBeforeUnmount(() => {
  if (flashTimer) clearTimeout(flashTimer)
})

watch(
  () => projects.selected,
  () => {
    briefFlash.value = ''
    expanded.value = {}
    showCreate.value = false
    showLink.value = false
  }
)

function isOpen(bucket: LandingBucket): boolean {
  return expanded.value[bucket.rel] ?? bucket.count > 0
}

function toggle(bucket: LandingBucket): void {
  expanded.value = { ...expanded.value, [bucket.rel]: !isOpen(bucket) }
}

function sendBrief(): void {
  const payload = projects.brief
  if (!payload) return
  conversation.setDraft(payload.text)
  briefFlash.value = t('studio.project.briefDone')
  if (flashTimer) clearTimeout(flashTimer)
  flashTimer = setTimeout(() => {
    briefFlash.value = ''
    flashTimer = null
  }, 2400)
}
</script>

<template>
  <section class="prj">
    <p v-if="projects.error" class="prj__error">
      <AlertCircle :size="14" />
      <span>{{ projects.error }}</span>
    </p>

    <header class="prj__bar">
      <label class="prj__filter">
        <FolderOpen :size="13" />
        <input v-model="projects.filter" type="search" :placeholder="t('studio.project.filter')" />
      </label>
      <button
        type="button"
        class="prj__btn"
        :disabled="projects.loadingShelf"
        @click="projects.refresh({ fresh: true })"
      >
        <LoaderCircle v-if="projects.loadingShelf" :size="13" class="is-spinning" />
        <RefreshCw v-else :size="13" />
        <span>{{ t('studio.project.refresh') }}</span>
      </button>
      <button type="button" class="prj__btn" :class="{ 'is-on': showCreate }" @click="showCreate = !showCreate">
        <Sparkles :size="13" />
        <span>{{ t('studio.project.create') }}</span>
      </button>
    </header>

    <div v-if="showCreate" class="prj__panel">
      <div class="prj__panelRow">
        <label class="prj__field">
          <span>{{ t('studio.project.createName') }}</span>
          <input v-model="projects.createName" type="text" spellcheck="false" />
        </label>
        <label class="prj__field is-narrow">
          <span>{{ t('studio.project.createEpisodes') }}</span>
          <input v-model.number="projects.createEpisodes" type="number" min="1" />
        </label>
        <label class="prj__check">
          <input v-model="projects.createUpgrade" type="checkbox" />
          <span>{{ t('studio.project.createUpgrade') }}</span>
        </label>
      </div>
      <div class="prj__panelRow">
        <label class="prj__field">
          <span>{{ t('studio.project.linkNovel') }}</span>
          <input
            v-model="projects.createNovel"
            type="text"
            spellcheck="false"
            :placeholder="t('studio.project.linkNovelPathHint')"
          />
        </label>
        <button
          type="button"
          class="prj__btn is-primary"
          :disabled="projects.creating || projects.createName.trim() === ''"
          @click="projects.create()"
        >
          <LoaderCircle v-if="projects.creating" :size="13" class="is-spinning" />
          <Sparkles v-else :size="13" />
          <span>{{ t('studio.project.createRun') }}</span>
        </button>
      </div>
      <p v-if="projects.lastCreate" class="prj__ok">
        {{
          t('studio.project.createDone', {
            name: projects.lastCreate.name,
            episodes: n(projects.lastCreate.episodes)
          })
        }}
        <span v-if="projects.lastCreate.pending.length">
          · {{ t('studio.project.pending', { count: n(projects.lastCreate.pending.length) }) }}
        </span>
      </p>
    </div>

    <div class="prj__split">
      <div class="prj__shelf">
        <p class="prj__meta">
          {{
            t('studio.project.count', {
              matched: n(projects.matched),
              returned: n(projects.visibleProjects.length)
            })
          }}
          <span v-if="projects.truncated" class="prj__warn">{{ t('studio.project.truncated') }}</span>
        </p>

        <p v-if="projects.loadingShelf && projects.projects.length === 0" class="prj__hint">
          {{ t('studio.project.loading') }}
        </p>
        <p v-else-if="!projects.exists" class="prj__hint">
          {{ t('studio.project.dirMissing', { dir: projects.dir }) }}
        </p>
        <p v-else-if="projects.visibleProjects.length === 0" class="prj__hint">
          {{ t('studio.project.empty') }}
        </p>

        <ul v-else class="prj__items">
          <li v-for="project in projects.visibleProjects" :key="project.name">
            <button
              type="button"
              class="prj__item"
              :class="{ 'is-active': project.name === projects.selected }"
              @click="projects.select(project.name)"
            >
              <span class="prj__itemName">{{ project.name }}</span>
              <span class="prj__itemMeta">{{ n(project.stages_done) }}/{{ n(project.stages_total) }}</span>
              <span v-if="project.missing_count > 0" class="prj__itemWarn">
                {{ t('studio.project.missingCount', { count: n(project.missing_count) }) }}
              </span>
            </button>
          </li>
        </ul>
      </div>

      <div class="prj__work" :class="{ 'is-editing': projects.file !== null }">
        <p v-if="projects.selected === ''" class="prj__hint">{{ t('studio.project.pick') }}</p>

        <div v-else class="prj__tree">
          <header class="prj__head">
            <span class="prj__name">{{ projects.selected }}</span>
            <span class="prj__path">
              {{
                projects.tree?.single_root
                  ? projects.tree.path
                  : `${projects.tree?.path} · ${projects.tree?.path_out}`
              }}
            </span>
          </header>

          <p class="prj__novel">
            {{
              projects.tree?.novel
                ? t('studio.project.novelLinked', { name: projects.tree.novel })
                : t('studio.project.novelUnlinked')
            }}
          </p>

          <div class="prj__actions">
            <button type="button" class="prj__btn" :disabled="projects.briefing" @click="projects.buildBrief()">
              <LoaderCircle v-if="projects.briefing" :size="13" class="is-spinning" />
              <Info v-else :size="13" />
              <span>{{ t('studio.project.brief') }}</span>
            </button>
            <button type="button" class="prj__btn" :disabled="projects.migrating" @click="projects.checkLayout()">
              <LoaderCircle v-if="projects.migrating" :size="13" class="is-spinning" />
              <Wrench v-else :size="13" />
              <span>{{ t('studio.project.migrate') }}</span>
            </button>
            <button type="button" class="prj__btn" :class="{ 'is-on': showLink }" @click="showLink = !showLink">
              <span>{{ t('studio.project.linkNovel') }}</span>
            </button>
            <span v-if="briefFlash" class="prj__ok">{{ briefFlash }}</span>
          </div>

          <div v-if="projects.brief" class="prj__brief">
            <p class="prj__briefText">{{ projects.brief.text }}</p>
            <button type="button" class="prj__btn is-primary" @click="sendBrief()">
              {{ t('studio.project.briefSend') }}
            </button>
          </div>

          <div v-if="showLink" class="prj__panel">
            <div class="prj__panelRow">
              <label class="prj__field">
                <span>{{ t('studio.project.linkNovelPath') }}</span>
                <input
                  v-model="projects.linkNovel"
                  type="text"
                  spellcheck="false"
                  :placeholder="t('studio.project.linkNovelPathHint')"
                />
              </label>
              <button
                type="button"
                class="prj__btn is-primary"
                :disabled="projects.linking || projects.linkNovel.trim() === ''"
                @click="projects.link()"
              >
                <LoaderCircle v-if="projects.linking" :size="13" class="is-spinning" />
                <span>{{ t('studio.project.linkNovelRun') }}</span>
              </button>
            </div>
            <p v-if="projects.lastLink" class="prj__meta">
              {{
                projects.lastLink.linked && !projects.lastLink.already
                  ? t('studio.project.linkNovelDone', { name: projects.lastLink.novel })
                  : t('studio.project.linkNovelAlready')
              }}
            </p>
          </div>

          <div v-if="projects.dryRun" class="prj__panel">
            <div class="prj__panelRow">
              <span class="prj__meta">
                {{
                  migrateApplied
                    ? t('studio.project.migrateDone')
                    : projects.dryRun.actions.length === 0
                      ? t('studio.project.migrateNoActions')
                      : t('studio.project.migrateActions', { count: n(projects.dryRun.actions.length) })
                }}
              </span>
              <button
                v-if="!migrateApplied && projects.dryRun.actions.length > 0"
                type="button"
                class="prj__btn is-primary"
                :disabled="projects.migrating"
                @click="projects.applyMigration()"
              >
                <LoaderCircle v-if="projects.migrating" :size="13" class="is-spinning" />
                <Wrench v-else :size="13" />
                <span>{{ t('studio.project.migrateRun') }}</span>
              </button>
            </div>
            <p v-if="tallies.length" class="prj__tally">
              <span v-for="tally in tallies" :key="tally.state" class="prj__chip" :class="`is-${tally.state}`">
                {{ `${tally.state} ${n(tally.count)}` }}
              </span>
            </p>
            <ul v-if="projects.dryRun.actions.length" class="prj__moves">
              <li v-for="action in projects.dryRun.actions" :key="`${action.state}:${action.rel}`">
                <span class="prj__moveState">{{ action.state }}</span>
                <span class="prj__moveRel">{{ action.src || action.rel }}</span>
                <span v-if="action.dst && action.dst !== action.rel" class="prj__moveDst">
                  → {{ action.dst }}
                </span>
              </li>
            </ul>
          </div>

          <p v-if="projects.loadingTree" class="prj__hint">{{ t('studio.project.loading') }}</p>

          <template v-else-if="projects.tree">
            <p v-if="projects.tree.summary.missing_count > 0" class="prj__warnBlock">
              {{ t('studio.project.notFound', { missing: projects.tree.summary.missing.join('、') }) }}
            </p>

            <div class="prj__stages">
              <div
                v-for="stage in projects.tree.summary.stages"
                :key="stage.rel"
                class="prj__stage"
                :class="{ 'is-done': stage.done }"
              >
                <span class="prj__stageLabel">{{ stage.label }}</span>
                <span class="prj__stageFiles">
                  {{
                    stage.files === 0
                      ? t('studio.project.stageEmpty')
                      : `${n(stage.files)} ${t('studio.project.files')}`
                  }}
                </span>
              </div>
            </div>

            <div v-for="shelf in projects.tree.shelves" :key="shelf.key" class="prj__shelfBlock">
              <p class="prj__shelfTitle">
                {{ shelf.title }}
                <span class="prj__meta">{{ n(shelf.count) }}</span>
                <span v-if="!shelf.exists" class="prj__warn">{{ t('studio.project.stageEmpty') }}</span>
              </p>

              <ul v-if="shelf.files && shelf.files.length" class="prj__files">
                <li v-for="entry in splitSeeds(shelf.files).real" :key="entry.rel">
                  <button
                    type="button"
                    class="prj__file"
                    :disabled="!entry.readable"
                    @click="projects.openFile(entry.rel)"
                  >
                    <FileText :size="12" />
                    <span class="prj__fileName">{{ entry.name }}</span>
                    <span class="prj__fileSize">{{ formatBytes(entry.bytes) }}</span>
                  </button>
                </li>
                <li v-for="entry in splitSeeds(shelf.files).seeds" :key="entry.rel" class="is-seed">
                  <button
                    type="button"
                    class="prj__file"
                    :disabled="!entry.readable"
                    @click="projects.openFile(entry.rel)"
                  >
                    <FileText :size="12" />
                    <span class="prj__fileName">{{ entry.name }}</span>
                    <span class="prj__fileSize">{{ formatBytes(entry.bytes) }}</span>
                  </button>
                </li>
              </ul>

              <template v-for="group in shelf.groups" :key="group.scope">
                <p class="prj__groupTitle">
                  {{ group.title }}
                  <span class="prj__meta">{{ n(group.count) }}</span>
                </p>
                <div v-for="bucket in group.dirs" :key="bucket.rel" class="prj__bucket">
                  <button type="button" class="prj__bucketHead" @click="toggle(bucket)">
                    <ChevronDown v-if="isOpen(bucket)" :size="12" />
                    <ChevronRight v-else :size="12" />
                    <span class="prj__bucketRel">{{ bucket.rel }}</span>
                    <span class="prj__meta">
                      {{ t('studio.project.files') }} {{ n(bucket.count) }}
                      <span v-if="bucket.seed_count">
                        · {{ t('studio.project.seedCount', { count: n(bucket.seed_count) }) }}
                      </span>
                      <span v-if="bucket.truncated">· {{ t('studio.project.truncated') }}</span>
                    </span>
                  </button>
                  <ul v-if="isOpen(bucket)" class="prj__files">
                    <li v-for="entry in splitSeeds(bucket.files).real" :key="entry.rel">
                      <button
                        type="button"
                        class="prj__file"
                        :disabled="!entry.readable"
                        @click="projects.openFile(entry.rel)"
                      >
                        <FileText :size="12" />
                        <span class="prj__fileName">{{ entry.name }}</span>
                        <span class="prj__fileSize">{{ formatBytes(entry.bytes) }}</span>
                      </button>
                    </li>
                    <li v-for="entry in splitSeeds(bucket.files).seeds" :key="entry.rel" class="is-seed">
                      <button
                        type="button"
                        class="prj__file"
                        :disabled="!entry.readable"
                        @click="projects.openFile(entry.rel)"
                      >
                        <FileText :size="12" />
                        <span class="prj__fileName">{{ entry.name }}</span>
                        <span class="prj__fileSize">{{ formatBytes(entry.bytes) }}</span>
                      </button>
                    </li>
                  </ul>
                </div>
              </template>
            </div>

            <p v-if="projects.tree.unknown.length" class="prj__meta">
              {{ t('studio.project.unknown', { names: projects.tree.unknown.join('、') }) }}
            </p>
          </template>
        </div>

        <div v-if="projects.file" class="prj__editor">
          <header class="prj__head">
            <span class="prj__fileName2">{{ projects.file.rel }}</span>
            <button type="button" class="prj__icon" @click="projects.closeFile()">
              <X :size="14" />
            </button>
          </header>

          <p v-if="projects.file.truncated" class="prj__warnBlock">
            {{ t('studio.project.tooLong') }}
          </p>
          <p v-if="projects.fileError" class="prj__error">
            <AlertCircle :size="13" />
            <span>{{ projects.fileError }}</span>
          </p>
          <p v-if="projects.savingOk && !projects.dirty" class="prj__ok">
            {{ t('studio.project.saved') }}
          </p>

          <textarea v-model="projects.draft" class="prj__text" spellcheck="false" :readonly="!projects.editable" />

          <footer class="prj__row">
            <span class="prj__meta">
              {{ projects.file.encoding }} · {{ t('studio.project.chars', { count: n(projects.file.total_chars) }) }}
            </span>
            <button
              type="button"
              class="prj__btn is-primary"
              :disabled="!projects.editable || !projects.dirty || projects.saving"
              @click="projects.saveFile()"
            >
              <LoaderCircle v-if="projects.saving" :size="13" class="is-spinning" />
              <Save v-else :size="13" />
              <span>{{ t('studio.project.save') }}</span>
            </button>
          </footer>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.prj {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  height: 100%;
}

.prj__error,
.prj__warnBlock {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  padding: 6px 8px;
  border-radius: 6px;
  font-size: 12px;
}

.prj__error {
  border: 1px solid var(--danger);
  color: var(--danger);
}

.prj__warnBlock {
  border: 1px solid var(--warning);
  color: var(--warning);
}

.prj__bar,
.prj__row,
.prj__panelRow,
.prj__actions,
.prj__tally,
.prj__head {
  display: flex;
  align-items: center;
  gap: 6px;
}

.prj__actions,
.prj__tally {
  flex-wrap: wrap;
}

.prj__filter {
  display: flex;
  flex: 1;
  align-items: center;
  gap: 6px;
  padding: 0 8px;
  border: 1px solid var(--studio-card-border);
  border-radius: 6px;
  background: var(--studio-card-bg);
  color: var(--text-faint);
}

.prj__filter input,
.prj__field input {
  flex: 1;
  min-width: 0;
  padding: 5px 0;
  border: 0;
  background: transparent;
  color: var(--text);
  font: inherit;
  outline: none;
}

.prj__field {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 3px;
  font-size: 11px;
  color: var(--text-faint);
}

.prj__field.is-narrow {
  flex: none;
  width: 72px;
}

.prj__field input {
  padding: 5px 8px;
  border: 1px solid var(--studio-card-border);
  border-radius: 6px;
  background: var(--studio-card-bg);
}

.prj__check {
  display: flex;
  align-items: center;
  gap: 5px;
  color: var(--text-muted);
  font-size: 11px;
}

.prj__btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 9px;
  border: 1px solid var(--studio-card-border);
  border-radius: 6px;
  background: var(--studio-card-bg);
  color: var(--text-muted);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.prj__btn:hover:not(:disabled) {
  color: var(--text);
  border-color: var(--accent);
}

.prj__btn:disabled {
  opacity: 0.45;
  cursor: default;
}

.prj__btn.is-primary {
  border-color: var(--accent);
  color: var(--accent);
}

.prj__btn.is-on {
  border-color: var(--accent);
  color: var(--accent);
}

.prj__icon {
  flex: none;
  padding: 3px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--text-faint);
  cursor: pointer;
}

.prj__icon:hover {
  color: var(--text);
}

.prj__panel,
.prj__brief {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px;
  border: 1px solid var(--studio-card-border);
  border-radius: 6px;
  background: var(--studio-card-bg);
}

.prj__brief {
  border-color: var(--accent);
}

.prj__briefText {
  margin: 0;
  max-height: 160px;
  overflow: auto;
  color: var(--text-muted);
  font-family: 'Cascadia Mono', 'Consolas', monospace;
  font-size: 11px;
  line-height: 1.6;
  white-space: pre-wrap;
}

.prj__hint,
.prj__meta,
.prj__path,
.prj__novel {
  margin: 0;
  color: var(--text-faint);
  font-size: 11px;
  line-height: 1.5;
}

.prj__novel {
  color: var(--text-muted);
}

.prj__ok {
  margin: 0;
  color: var(--success);
  font-size: 11px;
}

.prj__warn {
  margin-left: 6px;
  color: var(--warning);
}

.prj__split {
  display: grid;
  grid-template-columns: minmax(140px, 210px) 1fr;
  gap: 8px;
  flex: 1;
  min-height: 0;
}

.prj__shelf {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 0;
  overflow: auto;
  padding-right: 8px;
  border-right: 1px solid var(--studio-card-border);
}

.prj__work {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
  min-height: 0;
}

.prj__work.is-editing {
  grid-template-columns: 1fr minmax(260px, 380px);
}

.prj__tree,
.prj__editor {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 0;
  overflow: auto;
}

.prj__items,
.prj__files,
.prj__moves {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.prj__item,
.prj__file,
.prj__bucketHead {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  min-width: 0;
  padding: 4px 6px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  font: inherit;
  font-size: 12px;
  text-align: left;
  cursor: pointer;
}

.prj__bucketHead {
  font-size: 11px;
}

.prj__item:hover,
.prj__file:hover:not(:disabled),
.prj__bucketHead:hover {
  background: var(--studio-card-bg);
  color: var(--text);
}

.prj__item.is-active {
  border-color: var(--accent);
  color: var(--accent);
}

.prj__file:disabled {
  opacity: 0.45;
  cursor: default;
}

.prj__itemName,
.prj__fileName,
.prj__bucketRel,
.prj__moveRel {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.prj__fileName2 {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text);
  font-family: 'Cascadia Mono', 'Consolas', monospace;
  font-size: 11px;
}

.prj__itemMeta,
.prj__fileSize,
.prj__stageFiles {
  flex: none;
  color: var(--text-faint);
  font-size: 10px;
  font-variant-numeric: tabular-nums;
}

.prj__itemWarn,
.prj__moveState {
  flex: none;
  color: var(--warning);
  font-size: 10px;
}

.prj__files li.is-seed .prj__fileName {
  color: var(--text-faint);
}

.prj__shelfTitle,
.prj__groupTitle {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin: 4px 0 2px;
  color: var(--text);
  font-size: 12px;
  font-weight: 600;
}

.prj__groupTitle {
  font-weight: 400;
  color: var(--text-muted);
  font-size: 11px;
}

.prj__bucket {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-left: 10px;
}

.prj__stages {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.prj__stage {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 4px 7px;
  border: 1px solid var(--studio-card-border);
  border-left: 2px solid var(--text-faint);
  border-radius: 5px;
  background: var(--studio-card-bg);
}

.prj__stage.is-done {
  border-left-color: var(--success);
}

.prj__stageLabel {
  color: var(--text-muted);
  font-size: 11px;
}

.prj__stage.is-done .prj__stageLabel {
  color: var(--text);
}

.prj__chip {
  padding: 1px 6px;
  border: 1px solid var(--studio-card-border);
  border-radius: 8px;
  color: var(--text-muted);
  font-size: 10px;
}

.prj__chip.is-conflict,
.prj__chip.is-failed {
  border-color: var(--danger);
  color: var(--danger);
}

.prj__chip.is-moved {
  border-color: var(--success);
  color: var(--success);
}

.prj__moves li {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-size: 11px;
  color: var(--text-muted);
}

.prj__moveDst {
  color: var(--text-faint);
}

.prj__text {
  flex: 1;
  min-height: 200px;
  padding: 8px 10px;
  border: 1px solid var(--studio-card-border);
  border-radius: 6px;
  background: var(--studio-card-bg);
  color: var(--text);
  font-family: 'Cascadia Mono', 'Consolas', monospace;
  font-size: 12px;
  line-height: 1.7;
  resize: none;
  outline: none;
}

.prj__text:read-only {
  color: var(--text-muted);
}

.is-spinning {
  animation: prj-spin 900ms linear infinite;
}

@keyframes prj-spin {
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
