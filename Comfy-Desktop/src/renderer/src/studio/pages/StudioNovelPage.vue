<script setup lang="ts">
/**
 * The novel shelf: pick a text, read it, find your way around it, and quote it
 * into the conversation.
 *
 * The reading pane is deliberately plain text in a `<pre>` — the host hands back
 * a character window and the offsets around it, and anything cleverer (markdown,
 * syntax colouring) would only make "quote exactly these characters" harder to
 * get right. Chapter jumps, search hits and paging all funnel through
 * `openAt(offset)`, so there is one definition of "go there".
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  AlertCircle,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Import,
  LoaderCircle,
  Quote,
  RefreshCw,
  Search,
  Trash2
} from 'lucide-vue-next'
import { useConversationStore } from '../../stores/conversationStore'
import { useNovelsStore } from '../../stores/novelsStore'
import { formatBytes } from './novels'

const novels = useNovelsStore()
const conversation = useConversationStore()
const { t, n } = useI18n()

type Tab = 'text' | 'chapters' | 'search'
const tab = ref<Tab>('text')
const showImport = ref(false)
const quoteFlash = ref('')
const bodyRef = ref<HTMLElement | null>(null)
let flashTimer: ReturnType<typeof setTimeout> | null = null

const rangeLabel = computed(() => {
  const page = novels.page
  if (!page) return ''
  return t('studio.novel.range', {
    from: n(page.offset),
    to: n(page.offset + page.text.length),
    total: n(page.total_chars)
  })
})

onMounted(() => {
  if (!novels.loadedShelf) void novels.refresh()
})

// A stale flash from the previous novel would read as if it were about this one.
watch(
  () => novels.selected,
  () => {
    quoteFlash.value = ''
    tab.value = 'text'
  }
)

function flash(key: string): void {
  quoteFlash.value = key
  if (flashTimer) clearTimeout(flashTimer)
  flashTimer = setTimeout(() => {
    quoteFlash.value = ''
    flashTimer = null
  }, 2400)
}

/**
 * Quote the current selection, or the whole window when nothing is selected.
 *
 * Offsets have to be exact, so this only trusts the DOM when both ends of the
 * range sit in the same text node — which is the case for a plain `<pre>`. Any
 * other shape (a selection dragged in from elsewhere) falls back to the whole
 * window rather than inventing an offset that would not survive a re-read.
 */
function quote(): void {
  const page = novels.page
  const element = bodyRef.value
  if (!page || !element) return

  let start = 0
  let end = page.text.length
  const selection = window.getSelection()
  if (selection && selection.rangeCount > 0 && !selection.isCollapsed) {
    const range = selection.getRangeAt(0)
    const node = element.firstChild
    if (node && range.startContainer === node && range.endContainer === node) {
      start = range.startOffset
      end = range.endOffset
    }
  }

  const text = page.text.slice(start, end).trim()
  if (text === '') {
    flash('studio.novel.quoteEmpty')
    return
  }

  const accepted = conversation.addQuote({
    name: page.name,
    offset: page.offset + start,
    chars: text.length,
    text
  })
  flash(accepted ? 'studio.novel.quoteAdded' : 'studio.novel.quoteLimit')
}
</script>

<template>
  <section class="novel">
    <p v-if="novels.error" class="novel__error">
      <AlertCircle :size="14" />
      <span>{{ novels.error }}</span>
    </p>

    <header class="novel__bar">
      <label class="novel__filter">
        <Search :size="13" />
        <input
          v-model="novels.filter"
          type="search"
          :placeholder="t('studio.novel.filter')"
        />
      </label>
      <button type="button" class="novel__btn" :disabled="novels.loadingShelf" @click="novels.refresh()">
        <LoaderCircle v-if="novels.loadingShelf" :size="13" class="is-spinning" />
        <RefreshCw v-else :size="13" />
        <span>{{ t('studio.novel.refresh') }}</span>
      </button>
      <button
        type="button"
        class="novel__btn"
        :class="{ 'is-on': showImport }"
        @click="showImport = !showImport"
      >
        <Import :size="13" />
        <span>{{ t('studio.novel.import') }}</span>
      </button>
    </header>

    <div v-if="showImport" class="novel__import">
      <p class="novel__importHint">{{ t('studio.novel.importHint') }}</p>
      <label class="novel__field">
        <span>{{ t('studio.novel.importPath') }}</span>
        <input
          v-model="novels.importPath"
          type="text"
          spellcheck="false"
          :placeholder="t('studio.novel.importPathHint')"
        />
      </label>
      <label class="novel__field">
        <span>{{ t('studio.novel.importName') }}</span>
        <input
          v-model="novels.importName"
          type="text"
          spellcheck="false"
          :placeholder="t('studio.novel.importNameHint')"
        />
      </label>

      <div v-if="novels.overwritePrompt" class="novel__overwrite">
        <span>{{ t('studio.novel.importOverwriteAsk', { name: novels.overwritePrompt }) }}</span>
        <button type="button" class="novel__btn is-danger" :disabled="novels.importing" @click="novels.importFile(true)">
          {{ t('studio.novel.importOverwrite') }}
        </button>
        <button type="button" class="novel__btn" @click="novels.cancelOverwrite()">
          {{ t('studio.novel.cancel') }}
        </button>
      </div>

      <div v-else class="novel__row">
        <button
          type="button"
          class="novel__btn is-primary"
          :disabled="novels.importing || novels.importPath.trim() === ''"
          @click="novels.importFile()"
        >
          <LoaderCircle v-if="novels.importing" :size="13" class="is-spinning" />
          <Import v-else :size="13" />
          <span>{{ t('studio.novel.importRun') }}</span>
        </button>
        <span v-if="novels.lastImport?.imported" class="novel__ok">
          {{
            t('studio.novel.importDone', {
              name: novels.lastImport.name,
              size: formatBytes(novels.lastImport.bytes)
            })
          }}
        </span>
      </div>
    </div>

    <div class="novel__split">
      <div class="novel__shelf">
        <p class="novel__meta">
          {{
            t('studio.novel.count', {
              matched: n(novels.matched),
              returned: n(novels.visibleEntries.length)
            })
          }}
          <span v-if="novels.truncated" class="novel__warn">{{ t('studio.novel.truncated') }}</span>
        </p>

        <p v-if="novels.loadingShelf && novels.entries.length === 0" class="novel__hint">
          {{ t('studio.novel.loading') }}
        </p>
        <p v-else-if="!novels.exists" class="novel__hint">
          {{ t('studio.novel.dirMissing', { dir: novels.dir }) }}
        </p>
        <p v-else-if="novels.visibleEntries.length === 0" class="novel__hint">
          {{ t('studio.novel.empty') }}
        </p>

        <ul v-else class="novel__items">
          <li v-for="entry in novels.visibleEntries" :key="entry.name">
            <button
              type="button"
              class="novel__item"
              :class="{ 'is-active': entry.name === novels.selected }"
              :disabled="!entry.text"
              @click="novels.select(entry.name)"
            >
              <BookOpen :size="13" />
              <span class="novel__itemName">{{ entry.name }}</span>
              <span class="novel__itemSize">{{ formatBytes(entry.bytes) }}</span>
              <span v-if="!entry.text" class="novel__itemWarn">
                {{ t('studio.novel.notText') }}
              </span>
            </button>
            <button
              v-if="entry.name !== novels.deleteTarget"
              type="button"
              class="novel__icon"
              :title="t('studio.novel.delete')"
              @click="novels.armDelete(entry.name)"
            >
              <Trash2 :size="13" />
            </button>
            <span v-else class="novel__confirm">
              <button type="button" class="novel__btn is-danger" @click="novels.remove(entry.name)">
                {{ t('studio.novel.delete') }}
              </button>
              <button type="button" class="novel__btn" @click="novels.cancelDelete()">
                {{ t('studio.novel.cancel') }}
              </button>
            </span>
          </li>
        </ul>
      </div>

      <div class="novel__reader">
        <p v-if="novels.selected === ''" class="novel__hint">
          {{ t('studio.novel.noSelection') }}
        </p>

        <template v-else>
          <header class="novel__readerHead">
            <span class="novel__readerName">{{ novels.selected }}</span>
            <span v-if="novels.page" class="novel__enc">
              {{ t('studio.novel.encoding', { encoding: novels.page.encoding }) }}
            </span>
            <button type="button" class="novel__btn" :disabled="!novels.page" @click="quote()">
              <Quote :size="13" />
              <span>{{ t('studio.novel.quote') }}</span>
            </button>
          </header>

          <p v-if="quoteFlash" class="novel__flash" :class="{ 'is-bad': quoteFlash.endsWith('Limit') || quoteFlash.endsWith('Empty') }">
            {{ t(quoteFlash) }}
          </p>

          <nav class="novel__tabs">
            <button type="button" :class="{ 'is-on': tab === 'text' }" @click="tab = 'text'">
              {{ t('studio.novel.tab.text') }}
            </button>
            <button type="button" :class="{ 'is-on': tab === 'chapters' }" @click="tab = 'chapters'">
              {{ t('studio.novel.tab.chapters') }}
            </button>
            <button type="button" :class="{ 'is-on': tab === 'search' }" @click="tab = 'search'">
              {{ t('studio.novel.tab.search') }}
            </button>
          </nav>

          <p v-if="novels.reading" class="novel__hint">{{ t('studio.novel.loading') }}</p>

          <template v-else-if="tab === 'text'">
            <pre ref="bodyRef" class="novel__text">{{ novels.page?.text ?? '' }}</pre>
            <footer class="novel__pager">
              <button
                type="button"
                class="novel__btn"
                :disabled="!novels.page || novels.page.offset === 0"
                @click="novels.previousPage()"
              >
                <ChevronLeft :size="13" />
                <span>{{ t('studio.novel.prev') }}</span>
              </button>
              <span class="novel__range">{{ rangeLabel }}</span>
              <button
                type="button"
                class="novel__btn"
                :disabled="!novels.page || novels.page.at_end"
                @click="novels.nextPage()"
              >
                <span>{{ t('studio.novel.next') }}</span>
                <ChevronRight :size="13" />
              </button>
            </footer>
          </template>

          <template v-else-if="tab === 'chapters'">
            <p v-if="novels.loadingChapters" class="novel__hint">{{ t('studio.novel.loading') }}</p>
            <p v-else-if="novels.chapters && novels.chapters.message" class="novel__hint">
              {{ t('studio.novel.chaptersMessage') }}
            </p>
            <p v-else-if="!novels.chapters || novels.chapters.chapters.length === 0" class="novel__hint">
              {{ t('studio.novel.chaptersEmpty') }}
            </p>
            <ul v-else class="novel__hits">
              <li v-for="(chapter, index) in novels.chapters.chapters" :key="chapter.offset">
                <button
                  type="button"
                  class="novel__hit"
                  :class="{ 'is-active': index === novels.currentChapter }"
                  @click="novels.openAt(chapter.offset)"
                >
                  <span class="novel__hitTitle">{{ chapter.title }}</span>
                  <span class="novel__hitWhere">{{ n(chapter.offset) }}</span>
                </button>
              </li>
            </ul>
          </template>

          <template v-else>
            <form class="novel__search" @submit.prevent="novels.search()">
              <input
                v-model="novels.query"
                type="search"
                :placeholder="t('studio.novel.searchPlaceholder')"
              />
              <button type="submit" class="novel__btn" :disabled="novels.searching">
                <LoaderCircle v-if="novels.searching" :size="13" class="is-spinning" />
                <Search v-else :size="13" />
                <span>{{ t('studio.novel.searchRun') }}</span>
              </button>
            </form>

            <p v-if="novels.searched" class="novel__meta">
              {{ t('studio.novel.searchCount', { count: n(novels.searchMatched) }) }}
              <span v-if="novels.searchTruncated" class="novel__warn">
                {{ t('studio.novel.searchTruncated') }}
              </span>
            </p>
            <p v-if="novels.searched && novels.matches.length === 0" class="novel__hint">
              {{ t('studio.novel.searchEmpty') }}
            </p>
            <ul v-else class="novel__hits">
              <li v-for="match in novels.matches" :key="match.offset">
                <button type="button" class="novel__hit" @click="novels.openAt(match.offset)">
                  <span class="novel__hitWhere">{{ n(match.offset) }}</span>
                  <span class="novel__snippet">{{ match.snippet }}</span>
                </button>
              </li>
            </ul>
          </template>
        </template>
      </div>
    </div>
  </section>
</template>

<style scoped>
.novel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  height: 100%;
}

.novel__error {
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

.novel__bar,
.novel__row,
.novel__pager,
.novel__search,
.novel__readerHead {
  display: flex;
  align-items: center;
  gap: 6px;
}

.novel__filter {
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

.novel__filter input,
.novel__field input,
.novel__search input {
  flex: 1;
  min-width: 0;
  padding: 5px 0;
  border: 0;
  background: transparent;
  color: var(--text);
  font: inherit;
  outline: none;
}

.novel__field {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 11px;
  color: var(--text-faint);
}

.novel__field input {
  padding: 5px 8px;
  border: 1px solid var(--studio-card-border);
  border-radius: 6px;
  background: var(--studio-card-bg);
}

.novel__search {
  margin-bottom: 6px;
}

.novel__search input {
  padding: 5px 8px;
  border: 1px solid var(--studio-card-border);
  border-radius: 6px;
  background: var(--studio-card-bg);
}

.novel__btn {
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

.novel__btn:hover:not(:disabled) {
  color: var(--text);
  border-color: var(--accent);
}

.novel__btn:disabled {
  opacity: 0.45;
  cursor: default;
}

.novel__btn.is-primary {
  border-color: var(--accent);
  color: var(--accent);
}

.novel__btn.is-danger {
  border-color: var(--danger);
  color: var(--danger);
}

.novel__btn.is-on {
  border-color: var(--accent);
  color: var(--accent);
}

.novel__import {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px;
  border: 1px solid var(--studio-card-border);
  border-radius: 6px;
  background: var(--studio-card-bg);
}

.novel__importHint,
.novel__hint,
.novel__meta {
  margin: 0;
  color: var(--text-faint);
  font-size: 11px;
  line-height: 1.5;
}

.novel__overwrite {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  color: var(--warning);
  font-size: 12px;
}

.novel__ok {
  color: var(--success);
  font-size: 11px;
}

.novel__warn {
  margin-left: 6px;
  color: var(--warning);
}

.novel__split {
  display: grid;
  grid-template-columns: minmax(140px, 210px) 1fr;
  gap: 8px;
  flex: 1;
  min-height: 0;
}

.novel__shelf,
.novel__reader {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 0;
  overflow: auto;
}

.novel__shelf {
  border-right: 1px solid var(--studio-card-border);
  padding-right: 8px;
}

.novel__items,
.novel__hits {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.novel__items li {
  display: flex;
  align-items: center;
  gap: 4px;
}

.novel__item,
.novel__hit {
  display: flex;
  flex: 1;
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

.novel__hit {
  flex-direction: column;
  align-items: stretch;
  gap: 2px;
}

.novel__item:hover:not(:disabled),
.novel__hit:hover {
  background: var(--studio-card-bg);
  color: var(--text);
}

.novel__item.is-active,
.novel__hit.is-active {
  border-color: var(--accent);
  color: var(--accent);
}

.novel__item:disabled {
  opacity: 0.5;
  cursor: default;
}

.novel__itemName,
.novel__hitTitle {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.novel__snippet {
  color: var(--text-faint);
  font-size: 11px;
  overflow-wrap: anywhere;
}

.novel__hitWhere {
  color: var(--text-faint);
  font-size: 10px;
  font-variant-numeric: tabular-nums;
}

.novel__itemSize {
  flex: none;
  color: var(--text-faint);
  font-size: 10px;
}

.novel__itemWarn {
  flex: none;
  color: var(--warning);
  font-size: 10px;
}

.novel__icon {
  flex: none;
  padding: 3px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--text-faint);
  cursor: pointer;
}

.novel__icon:hover {
  color: var(--danger);
}

.novel__confirm {
  display: inline-flex;
  gap: 4px;
}

.novel__readerName {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text);
  font-family: 'Cascadia Mono', 'Consolas', monospace;
  font-size: 12px;
}

.novel__enc,
.novel__range {
  color: var(--text-faint);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.novel__flash {
  margin: 0;
  color: var(--success);
  font-size: 11px;
}

.novel__flash.is-bad {
  color: var(--warning);
}

.novel__tabs {
  display: flex;
  gap: 2px;
}

.novel__tabs button {
  padding: 4px 10px;
  border: 1px solid transparent;
  border-radius: 6px 6px 0 0;
  background: transparent;
  color: var(--text-faint);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.novel__tabs button.is-on {
  border-color: var(--studio-card-border);
  border-bottom-color: transparent;
  color: var(--text);
}

.novel__text {
  flex: 1;
  margin: 0;
  min-height: 180px;
  padding: 8px 10px;
  border: 1px solid var(--studio-card-border);
  border-radius: 6px;
  background: var(--studio-card-bg);
  color: var(--text);
  font-family: 'Cascadia Mono', 'Consolas', monospace;
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  overflow: auto;
}

.novel__pager {
  gap: 8px;
}

.novel__range {
  flex: 1;
  text-align: center;
}

.is-spinning {
  animation: novel-spin 900ms linear infinite;
}

@keyframes novel-spin {
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
