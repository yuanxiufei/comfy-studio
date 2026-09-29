/**
 * Projects, driven by `projects/*`.
 *
 * The only stateful subtlety is the editor's `base_digest`: the host refuses a
 * write whose base no longer matches, which is how two windows can't clobber
 * each other. So the digest is remembered alongside the text, refreshed on every
 * successful save (the host echoes the new one), and *dropped* on a conflict —
 * forcing a reopen rather than letting the user re-save on top of a file they
 * have not actually seen.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  PROJECT_DEFAULT_EPISODES,
  PROJECT_LIST_LIMIT,
  PROJECT_READ_CHARS,
  type LinkNovelPayload,
  type ProjectBriefPayload,
  type ProjectCreatePayload,
  type ProjectListPayload,
  type ProjectMigratePayload,
  type ProjectReadPayload,
  type ProjectSummary,
  type ProjectTreePayload,
  type ProjectWritePayload
} from '../studio/pages/projects'
import { callStudio } from '../studio/pages/rpc'

export const useProjectsStore = defineStore('studioProjects', () => {
  // ---- list ----
  const projects = ref<ProjectSummary[]>([])
  const dir = ref('')
  const dirOut = ref('')
  const singleRoot = ref(true)
  const exists = ref(true)
  const matched = ref(0)
  const truncated = ref(false)
  const filter = ref('')
  const loadingShelf = ref(false)
  const loadedShelf = ref(false)

  // ---- selection ----
  const selected = ref('')
  const tree = ref<ProjectTreePayload | null>(null)
  const loadingTree = ref(false)

  // ---- editor ----
  const openRel = ref('')
  const file = ref<ProjectReadPayload | null>(null)
  const draft = ref('')
  const saving = ref(false)
  const savingOk = ref(false)
  const fileError = ref<string | null>(null)

  // ---- migrate / create / link / brief ----
  const dryRun = ref<ProjectMigratePayload | null>(null)
  const migrating = ref(false)
  const createName = ref('')
  const createEpisodes = ref(PROJECT_DEFAULT_EPISODES)
  const createUpgrade = ref(true)
  const createNovel = ref('')
  const creating = ref(false)
  const lastCreate = ref<ProjectCreatePayload | null>(null)
  const linkNovel = ref('')
  const linking = ref(false)
  const lastLink = ref<LinkNovelPayload | null>(null)
  const brief = ref<ProjectBriefPayload | null>(null)
  const briefing = ref(false)

  const error = ref<string | null>(null)

  const visibleProjects = computed(() => {
    const needle = filter.value.trim().toLowerCase()
    if (needle === '') return projects.value
    return projects.value.filter((project) => project.name.toLowerCase().includes(needle))
  })

  const dirty = computed(() => file.value !== null && draft.value !== file.value.text)
  const editable = computed(() => file.value !== null && !file.value.truncated)

  function closeFile(): void {
    openRel.value = ''
    file.value = null
    draft.value = ''
    fileError.value = null
    savingOk.value = false
  }

  function clearSelection(): void {
    selected.value = ''
    tree.value = null
    closeFile()
    dryRun.value = null
    brief.value = null
    lastLink.value = null
  }

  async function refresh(): Promise<void> {
    loadingShelf.value = true
    const outcome = await callStudio<ProjectListPayload>('projects/list', {
      limit: PROJECT_LIST_LIMIT
    })
    loadingShelf.value = false
    loadedShelf.value = true
    if (!outcome.ok || !outcome.value) {
      error.value = outcome.error
      return
    }
    error.value = null
    projects.value = outcome.value.projects
    dir.value = outcome.value.dir
    dirOut.value = outcome.value.dir_out
    singleRoot.value = outcome.value.single_root
    exists.value = outcome.value.exists
    matched.value = outcome.value.matched
    truncated.value = outcome.value.truncated
    if (selected.value && !outcome.value.projects.some((item) => item.name === selected.value)) {
      clearSelection()
    }
  }

  async function loadTree(): Promise<void> {
    if (!selected.value) return
    loadingTree.value = true
    const outcome = await callStudio<ProjectTreePayload>('projects/tree', { name: selected.value })
    loadingTree.value = false
    if (!outcome.ok || !outcome.value) {
      error.value = outcome.error
      return
    }
    tree.value = outcome.value
  }

  async function select(name: string): Promise<void> {
    if (name === selected.value) return
    selected.value = name
    tree.value = null
    closeFile()
    dryRun.value = null
    brief.value = null
    lastLink.value = null
    linkNovel.value = ''
    await loadTree()
  }

  /** Open a file. `rel` empty closes the editor. */
  async function openFile(rel: string): Promise<void> {
    if (rel === '') {
      closeFile()
      return
    }
    openRel.value = rel
    fileError.value = null
    savingOk.value = false
    const outcome = await callStudio<ProjectReadPayload>('projects/read', {
      name: selected.value,
      rel,
      chars: PROJECT_READ_CHARS
    })
    if (!outcome.ok || !outcome.value) {
      file.value = null
      draft.value = ''
      fileError.value = outcome.error
      return
    }
    file.value = outcome.value
    draft.value = outcome.value.text
  }

  async function saveFile(): Promise<void> {
    const current = file.value
    if (!current || !editable.value) return
    saving.value = true
    const outcome = await callStudio<ProjectWritePayload>('projects/write', {
      name: selected.value,
      rel: current.rel,
      text: draft.value,
      base_digest: current.digest
    })
    saving.value = false
    if (!outcome.ok || !outcome.value) {
      fileError.value = outcome.error
      savingOk.value = false
      // A refused write means the file on disk is not the one we read: reopen
      // before anything else is typed on top of it.
      file.value = null
      draft.value = ''
      return
    }
    fileError.value = null
    savingOk.value = true
    const written = outcome.value
    // The window now matches what was written, and the digest chains forward.
    file.value = { ...current, digest: written.digest, bytes: written.bytes, text: draft.value }
    if (dryRun.value) dryRun.value = null
    await Promise.all([loadTree(), refresh()])
  }

  async function checkLayout(): Promise<void> {
    if (!selected.value) return
    migrating.value = true
    const outcome = await callStudio<ProjectMigratePayload>('projects/migrate', {
      name: selected.value,
      dry: true
    })
    migrating.value = false
    if (!outcome.ok || !outcome.value) {
      error.value = outcome.error
      return
    }
    error.value = null
    dryRun.value = outcome.value
  }

  async function applyMigration(): Promise<void> {
    if (!selected.value) return
    migrating.value = true
    const outcome = await callStudio<ProjectMigratePayload>('projects/migrate', {
      name: selected.value,
      dry: false
    })
    migrating.value = false
    if (!outcome.ok || !outcome.value) {
      error.value = outcome.error
      return
    }
    error.value = null
    dryRun.value = outcome.value
    closeFile()
    await Promise.all([loadTree(), refresh()])
  }

  async function create(): Promise<void> {
    const name = createName.value.trim()
    if (name === '') return
    creating.value = true
    const outcome = await callStudio<ProjectCreatePayload>('projects/create', {
      name,
      episodes: createEpisodes.value,
      upgrade: createUpgrade.value,
      novel: createNovel.value.trim()
    })
    creating.value = false
    if (!outcome.ok || !outcome.value) {
      error.value = outcome.error
      lastCreate.value = null
      return
    }
    error.value = null
    lastCreate.value = outcome.value
    createName.value = ''
    createNovel.value = ''
    await refresh()
    await select(outcome.value.name)
  }

  async function link(): Promise<void> {
    const novel = linkNovel.value.trim()
    if (!selected.value || novel === '') return
    linking.value = true
    const outcome = await callStudio<LinkNovelPayload>('projects/link_novel', {
      name: selected.value,
      novel
    })
    linking.value = false
    if (!outcome.ok || !outcome.value) {
      error.value = outcome.error
      return
    }
    error.value = null
    lastLink.value = outcome.value
    await loadTree()
  }

  async function buildBrief(): Promise<void> {
    if (!selected.value) return
    briefing.value = true
    const outcome = await callStudio<ProjectBriefPayload>('projects/brief', {
      name: selected.value
    })
    briefing.value = false
    if (!outcome.ok || !outcome.value) {
      error.value = outcome.error
      return
    }
    error.value = null
    brief.value = outcome.value
  }

  function reset(): void {
    projects.value = []
    filter.value = ''
    loadedShelf.value = false
    createName.value = ''
    createEpisodes.value = PROJECT_DEFAULT_EPISODES
    createUpgrade.value = true
    createNovel.value = ''
    lastCreate.value = null
    clearSelection()
    error.value = null
  }

  return {
    projects,
    dir,
    dirOut,
    singleRoot,
    exists,
    matched,
    truncated,
    filter,
    loadingShelf,
    loadedShelf,
    selected,
    tree,
    loadingTree,
    openRel,
    file,
    draft,
    saving,
    savingOk,
    fileError,
    dryRun,
    migrating,
    createName,
    createEpisodes,
    createUpgrade,
    createNovel,
    creating,
    lastCreate,
    linkNovel,
    linking,
    lastLink,
    brief,
    briefing,
    error,
    visibleProjects,
    dirty,
    editable,
    refresh,
    select,
    loadTree,
    openFile,
    closeFile,
    saveFile,
    checkLayout,
    applyMigration,
    create,
    link,
    buildBrief,
    reset
  }
})
