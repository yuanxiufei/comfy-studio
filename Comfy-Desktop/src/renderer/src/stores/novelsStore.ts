/**
 * The novel shelf, driven by `novels/*`.
 *
 * Reading is the interesting part: the host hands back a window of characters
 * plus the offsets needed to keep walking, so the store never does string math
 * on the text itself — it only remembers which window it is showing. Chapter and
 * search hits both resolve to an offset and funnel through the same
 * `openAt(offset)` call, which keeps one definition of "jump there".
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  NOVEL_CHAPTER_LIMIT,
  NOVEL_LIST_LIMIT,
  NOVEL_READ_CHARS,
  NOVEL_SEARCH_LIMIT,
  chapterIndexAt,
  type NovelChaptersPayload,
  type NovelDeletePayload,
  type NovelEntry,
  type NovelImportPayload,
  type NovelListPayload,
  type NovelMatch,
  type NovelReadPayload
} from '../studio/pages/novels'
import { callStudio } from '../studio/pages/rpc'

export const useNovelsStore = defineStore('studioNovels', () => {
  // ---- shelf ----
  const entries = ref<NovelEntry[]>([])
  const dir = ref('')
  const exists = ref(true)
  const matched = ref(0)
  const truncated = ref(false)
  const limit = ref(NOVEL_LIST_LIMIT)
  const filter = ref('')
  const loadingShelf = ref(false)
  const loadedShelf = ref(false)

  // ---- current novel ----
  const selected = ref('')
  const page = ref<NovelReadPayload | null>(null)
  const reading = ref(false)
  const chapters = ref<NovelChaptersPayload | null>(null)
  const loadingChapters = ref(false)

  // ---- search ----
  const query = ref('')
  const matches = ref<NovelMatch[]>([])
  const searchMatched = ref(0)
  const searchTruncated = ref(false)
  const searching = ref(false)
  const searched = ref(false)

  // ---- import / delete ----
  const importPath = ref('')
  const importName = ref('')
  const importing = ref(false)
  /** Set while the host has told us the name is taken and is waiting for the
   *  user to say "yes, overwrite" — one question, asked once. */
  const overwritePrompt = ref('')
  /** The last import outcome, successful or refused, for the page to narrate. */
  const lastImport = ref<NovelImportPayload | null>(null)
  const deleteTarget = ref('')

  const error = ref<string | null>(null)

  const visibleEntries = computed(() => {
    const needle = filter.value.trim().toLowerCase()
    if (needle === '') return entries.value
    return entries.value.filter((entry) => entry.name.toLowerCase().includes(needle))
  })

  /** Which chapter the reader is currently inside, or -1. */
  const currentChapter = computed(() => {
    if (!chapters.value || !page.value) return -1
    return chapterIndexAt(chapters.value.chapters, page.value.offset)
  })

  function clearSelection(): void {
    selected.value = ''
    page.value = null
    chapters.value = null
    matches.value = []
    searchMatched.value = 0
    searchTruncated.value = false
    searched.value = false
  }

  async function refresh(): Promise<void> {
    loadingShelf.value = true
    const outcome = await callStudio<NovelListPayload>('novels/list', { limit: NOVEL_LIST_LIMIT })
    loadingShelf.value = false
    loadedShelf.value = true
    if (!outcome.ok || !outcome.value) {
      error.value = outcome.error
      return
    }
    error.value = null
    entries.value = outcome.value.novels
    dir.value = outcome.value.dir
    exists.value = outcome.value.exists
    matched.value = outcome.value.matched
    truncated.value = outcome.value.truncated
    limit.value = outcome.value.limit
    // The selection may have been deleted from under us (or never existed).
    if (selected.value && !outcome.value.novels.some((entry) => entry.name === selected.value)) {
      clearSelection()
    }
  }

  /** Load the reading window that contains `offset`. */
  async function openAt(offset: number, chars = NOVEL_READ_CHARS): Promise<void> {
    if (!selected.value) return
    reading.value = true
    const outcome = await callStudio<NovelReadPayload>('novels/read', {
      name: selected.value,
      offset: Math.max(0, offset),
      chars
    })
    reading.value = false
    if (!outcome.ok || !outcome.value) {
      error.value = outcome.error
      return
    }
    error.value = null
    page.value = outcome.value
  }

  async function select(name: string): Promise<void> {
    if (name === selected.value) return
    selected.value = name
    page.value = null
    chapters.value = null
    matches.value = []
    searched.value = false
    searchMatched.value = 0
    await Promise.all([openAt(0), loadChapters()])
  }

  async function nextPage(): Promise<void> {
    if (!page.value || page.value.at_end) return
    await openAt(page.value.next_offset)
  }

  async function previousPage(): Promise<void> {
    if (!page.value) return
    await openAt(Math.max(0, page.value.offset - page.value.chars))
  }

  async function loadChapters(): Promise<void> {
    if (!selected.value) return
    loadingChapters.value = true
    const outcome = await callStudio<NovelChaptersPayload>('novels/chapters', {
      name: selected.value,
      limit: NOVEL_CHAPTER_LIMIT
    })
    loadingChapters.value = false
    if (!outcome.ok || !outcome.value) {
      error.value = outcome.error
      return
    }
    chapters.value = outcome.value
  }

  async function search(): Promise<void> {
    const needle = query.value.trim()
    if (!selected.value || needle === '') return
    searching.value = true
    const outcome = await callStudio<{
      matched: number
      truncated: boolean
      matches: NovelMatch[]
    }>('novels/search', { name: selected.value, query: needle, limit: NOVEL_SEARCH_LIMIT })
    searching.value = false
    searched.value = true
    if (!outcome.ok || !outcome.value) {
      error.value = outcome.error
      return
    }
    matches.value = outcome.value.matches
    searchMatched.value = outcome.value.matched
    searchTruncated.value = outcome.value.truncated
  }

  function clearSearch(): void {
    query.value = ''
    matches.value = []
    searchMatched.value = 0
    searchTruncated.value = false
    searched.value = false
  }

  /**
   * Import a file. `overwrite` is only ever true after the host has told us the
   * name is taken, so a plain click can never silently replace a novel.
   */
  async function importFile(overwrite = false): Promise<void> {
    const source = importPath.value.trim()
    if (source === '') return
    importing.value = true
    const outcome = await callStudio<NovelImportPayload>('novels/import', {
      path: source,
      name: importName.value.trim(),
      overwrite
    })
    importing.value = false
    if (!outcome.ok || !outcome.value) {
      error.value = outcome.error
      lastImport.value = null
      overwritePrompt.value = ''
      return
    }
    error.value = null
    lastImport.value = outcome.value
    overwritePrompt.value = outcome.value.imported ? '' : outcome.value.name
    if (outcome.value.imported) {
      importPath.value = ''
      importName.value = ''
      await refresh()
    }
  }

  function cancelOverwrite(): void {
    overwritePrompt.value = ''
  }

  function armDelete(name: string): void {
    deleteTarget.value = name
  }

  function cancelDelete(): void {
    deleteTarget.value = ''
  }

  async function remove(name: string): Promise<void> {
    const outcome = await callStudio<NovelDeletePayload>('novels/delete', { name })
    deleteTarget.value = ''
    if (!outcome.ok || !outcome.value) {
      error.value = outcome.error
      return
    }
    error.value = null
    if (name === selected.value) clearSelection()
    await refresh()
  }

  function reset(): void {
    entries.value = []
    filter.value = ''
    loadedShelf.value = false
    importPath.value = ''
    importName.value = ''
    lastImport.value = null
    overwritePrompt.value = ''
    deleteTarget.value = ''
    clearSearch()
    clearSelection()
    error.value = null
  }

  return {
    entries,
    dir,
    exists,
    matched,
    truncated,
    limit,
    filter,
    loadingShelf,
    loadedShelf,
    selected,
    page,
    reading,
    chapters,
    loadingChapters,
    query,
    matches,
    searchMatched,
    searchTruncated,
    searching,
    searched,
    importPath,
    importName,
    importing,
    overwritePrompt,
    lastImport,
    deleteTarget,
    error,
    visibleEntries,
    currentChapter,
    refresh,
    select,
    openAt,
    nextPage,
    previousPage,
    loadChapters,
    search,
    clearSearch,
    importFile,
    cancelOverwrite,
    armDelete,
    cancelDelete,
    remove,
    reset
  }
})
