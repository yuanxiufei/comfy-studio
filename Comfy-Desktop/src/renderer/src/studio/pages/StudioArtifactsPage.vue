<script setup lang="ts">
/**
 * The artifact shelf: what every project has actually left on disk.
 *
 * The project page already shows one project's landings in full — this page is
 * the cross-project version of that question ("where did anything get made?"),
 * so it reads the *same* two namespaces through the *same* store rather than
 * keeping a second copy of `projects/list`. Two stores over one endpoint would
 * be two lists of projects that can disagree after a refresh, and the one that
 * went stale would not complain.
 *
 * The filter is local on purpose. `projectsStore.filter` belongs to the project
 * page (its shelf is filtered client-side too), and sharing it would mean typing
 * here silently re-filters a page the user is not looking at.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlertCircle, FolderOpen, LoaderCircle, PackageOpen, RefreshCw, Search } from 'lucide-vue-next'
import { useProjectsStore } from '../../stores/projectsStore'
import {
  STAGE_SAMPLE_SHOWN,
  byActivity,
  landedStages,
  pendingStages,
  shelfTallies
} from './artifacts'

const projects = useProjectsStore()
const { t, n } = useI18n()

const needle = ref('')

onMounted(() => {
  if (!projects.loadedShelf) void projects.refresh()
})

/** Filtered, then put in working order — most recently touched first. */
const visible = computed(() => {
  const query = needle.value.trim().toLowerCase()
  const rows = query
    ? projects.projects.filter((project) => project.name.toLowerCase().includes(query))
    : projects.projects
  return byActivity(rows)
})

const tallies = computed(() => shelfTallies(projects.projects))

const tree = computed(() => projects.tree)

/** Only the stages with something in them: a project with two stages done would
 *  otherwise be 11 rows of zeroes to scroll past. */
const landed = computed(() => (tree.value ? landedStages(tree.value.summary) : []))

const pending = computed(() => (tree.value ? pendingStages(tree.value.summary).length : 0))

const shelves = computed(() =>
  (tree.value?.shelves ?? []).map((shelf) => ({
    key: shelf.key,
    title: shelf.title,
    count: shelf.count,
    exists: shelf.exists
  }))
)

function sampleOf(paths: readonly string[]): string[] {
  return paths.slice(0, STAGE_SAMPLE_SHOWN)
}
</script>

<template>
  <section class="artifacts">
    <p v-if="projects.error" class="artifacts__error">
      <AlertCircle :size="14" />
      <span>{{ projects.error }}</span>
    </p>

    <header class="artifacts__bar">
      <label class="artifacts__filter">
        <Search :size="13" />
        <input v-model="needle" type="search" :placeholder="t('studio.artifacts.filter')" />
      </label>
      <button
        type="button"
        class="artifacts__btn"
        :disabled="projects.loadingShelf"
        @click="projects.refresh()"
      >
        <LoaderCircle v-if="projects.loadingShelf" :size="13" class="is-spinning" />
        <RefreshCw v-else :size="13" />
        <span>{{ t('studio.artifacts.refresh') }}</span>
      </button>
    </header>

    <p class="artifacts__tallies">
      {{
        t('studio.artifacts.tallies', {
          projects: n(tallies.projects),
          started: n(tallies.started),
          files: n(tallies.files)
        })
      }}
      <span class="artifacts__dim">
        {{
          t('studio.artifacts.stages', {
            done: n(tallies.stagesDone),
            total: n(tallies.stagesTotal)
          })
        }}
      </span>
      <span v-if="tallies.gaps > 0" class="artifacts__warn">
        {{ t('studio.artifacts.gaps', { count: n(tallies.gaps) }) }}
      </span>
    </p>

    <div class="artifacts__split">
      <div class="artifacts__shelf">
        <p v-if="projects.loadingShelf && projects.projects.length === 0" class="artifacts__hint">
          {{ t('studio.artifacts.loading') }}
        </p>
        <p v-else-if="!projects.exists" class="artifacts__hint">
          {{ t('studio.artifacts.dirMissing', { dir: projects.dir }) }}
        </p>
        <p v-else-if="visible.length === 0" class="artifacts__hint">
          {{ t('studio.artifacts.empty') }}
        </p>

        <ul v-else class="artifacts__items">
          <li v-for="project in visible" :key="project.name">
            <button
              type="button"
              class="artifacts__item"
              :class="{ 'is-active': project.name === projects.selected }"
              @click="projects.select(project.name)"
            >
              <PackageOpen :size="13" />
              <span class="artifacts__itemName">{{ project.name }}</span>
              <span class="artifacts__itemCount">{{ n(project.files) }}</span>
              <span
                v-if="project.missing_count > 0"
                class="artifacts__itemWarn"
                :title="t('studio.artifacts.gaps', { count: n(project.missing_count) })"
              >
                !
              </span>
            </button>
          </li>
        </ul>
      </div>

      <div class="artifacts__detail">
        <p v-if="projects.selected === ''" class="artifacts__hint">
          {{ t('studio.artifacts.noSelection') }}
        </p>

        <template v-else>
          <header class="artifacts__head">
            <FolderOpen :size="13" />
            <span class="artifacts__headName">{{ projects.selected }}</span>
            <span v-if="tree" class="artifacts__dim">
              {{ t('studio.artifacts.count', { files: n(tree.summary.files) }) }}
            </span>
          </header>

          <p v-if="projects.loadingTree" class="artifacts__hint">
            {{ t('studio.artifacts.loading') }}
          </p>

          <template v-else-if="tree">
            <ul v-if="shelves.length > 0" class="artifacts__shelves">
              <li v-for="shelf in shelves" :key="shelf.key" :class="{ 'is-absent': !shelf.exists }">
                <span class="artifacts__shelfTitle">{{ shelf.title }}</span>
                <span class="artifacts__dim">{{ n(shelf.count) }}</span>
              </li>
            </ul>

            <p v-if="landed.length === 0" class="artifacts__hint">
              {{ t('studio.artifacts.shelfEmpty') }}
            </p>
            <ul v-else class="artifacts__stages">
              <li v-for="stage in landed" :key="stage.rel" class="artifacts__stage">
                <div class="artifacts__stageHead">
                  <span class="artifacts__stageLabel">{{ stage.label }}</span>
                  <span class="artifacts__dim">{{ n(stage.files) }}</span>
                </div>
                <ul class="artifacts__samples">
                  <li v-for="rel in sampleOf(stage.sample)" :key="rel" class="artifacts__sample">
                    {{ rel }}
                  </li>
                </ul>
                <p v-if="stage.files > stage.sample.length" class="artifacts__dim">
                  {{ t('studio.artifacts.more', { count: n(stage.files - stage.sample.length) }) }}
                </p>
              </li>
            </ul>

            <p v-if="pending > 0" class="artifacts__dim">
              {{ t('studio.artifacts.pending', { count: n(pending) }) }}
            </p>

            <p v-if="tree.gaps.length > 0" class="artifacts__warn">
              {{ t('studio.artifacts.gapList', { items: tree.gaps.join(' · ') }) }}
            </p>
            <p v-if="tree.unknown.length > 0" class="artifacts__dim">
              {{ t('studio.artifacts.unknown', { items: tree.unknown.join(' · ') }) }}
            </p>
          </template>
        </template>
      </div>
    </div>
  </section>
</template>

<style scoped>
.artifacts {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  height: 100%;
}

.artifacts__error {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  padding: 6px 8px;
  border: 1px solid var(--danger);
  border-radius: 6px;
  color: var(--danger);
  font-size: 12px;
}

.artifacts__bar {
  display: flex;
  align-items: center;
  gap: 6px;
}

.artifacts__filter {
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

.artifacts__filter input {
  flex: 1;
  min-width: 0;
  padding: 5px 0;
  border: 0;
  background: transparent;
  color: var(--text);
  font: inherit;
  outline: none;
}

.artifacts__btn {
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

.artifacts__btn:hover:not(:disabled) {
  color: var(--text);
  border-color: var(--accent);
}

.artifacts__btn:disabled {
  opacity: 0.45;
  cursor: default;
}

.artifacts__tallies {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px;
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
}

.artifacts__hint,
.artifacts__dim {
  margin: 0;
  color: var(--text-faint);
  font-size: 11px;
  line-height: 1.5;
}

.artifacts__warn {
  margin: 0;
  color: var(--warning);
  font-size: 11px;
  line-height: 1.5;
}

.artifacts__split {
  display: grid;
  grid-template-columns: minmax(160px, 240px) 1fr;
  gap: 8px;
  flex: 1;
  min-height: 0;
}

.artifacts__shelf,
.artifacts__detail {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 0;
  overflow: auto;
}

.artifacts__shelf {
  border-right: 1px solid var(--studio-card-border);
  padding-right: 8px;
}

.artifacts__items,
.artifacts__shelves,
.artifacts__stages,
.artifacts__samples {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.artifacts__item {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 6px;
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

.artifacts__item:hover {
  background: var(--studio-card-bg);
  color: var(--text);
}

.artifacts__item.is-active {
  border-color: var(--accent);
  color: var(--accent);
}

.artifacts__itemName {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.artifacts__itemCount {
  flex: none;
  color: var(--text-faint);
  font-size: 10px;
  font-variant-numeric: tabular-nums;
}

.artifacts__itemWarn {
  flex: none;
  color: var(--warning);
  font-size: 10px;
}

.artifacts__head {
  display: flex;
  align-items: center;
  gap: 6px;
}

.artifacts__headName {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text);
  font-family: 'Cascadia Mono', 'Consolas', monospace;
  font-size: 12px;
}

.artifacts__shelves {
  gap: 4px;
}

.artifacts__shelves li {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.artifacts__shelves li.is-absent {
  opacity: 0.5;
}

.artifacts__shelfTitle {
  color: var(--text-muted);
  font-size: 12px;
}

.artifacts__stage {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 5px 0;
  border-top: 1px solid var(--studio-card-border);
}

.artifacts__stageHead {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.artifacts__stageLabel {
  flex: 1;
  min-width: 0;
  color: var(--text);
  font-size: 12px;
}

.artifacts__sample {
  color: var(--text-faint);
  font-family: 'Cascadia Mono', 'Consolas', monospace;
  font-size: 11px;
  overflow-wrap: anywhere;
}

.is-spinning {
  animation: artifacts-spin 900ms linear infinite;
}

@keyframes artifacts-spin {
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
