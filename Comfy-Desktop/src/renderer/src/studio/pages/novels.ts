/**
 * Shapes and pure helpers for the novel shelf (`novels/*`).
 *
 * Kept out of the store so the fiddly bits — which chapter a reader offset
 * falls in, how a byte count reads — can be unit-tested without a host. The
 * shapes mirror `lib/comfy_studio/novels.py` field for field; every one of them
 * is a *host* payload, so nothing here invents a value the host didn't send.
 */

/** One file in the novel directory. `name` is a POSIX path relative to the
 *  library root (`sub/书名.txt`), and is the handle every other call takes. */
export interface NovelEntry {
  name: string
  path: string
  bytes: number
  /** Seconds since epoch (`st_mtime`). */
  mtime: number
  /** False for anything that is not `.txt`/`.md`: listed, but not readable. */
  text: boolean
}

/** `novels/list`. `exists: false` means the directory hasn't been created yet —
 *  a normal state for a fresh checkout, not an error. */
export interface NovelListPayload {
  dir: string
  exists: boolean
  matched: number
  returned: number
  truncated: boolean
  limit: number
  novels: NovelEntry[]
}

/** `novels/read`. Paging is by characters; `next_offset` is fed straight back. */
export interface NovelReadPayload {
  name: string
  path: string
  bytes: number
  mtime: number
  /** `utf-8` / `utf-16` / `gb18030` — the detected encoding, shown, not guessed. */
  encoding: string
  total_chars: number
  offset: number
  chars: number
  requested_chars: number
  next_offset: number
  at_end: boolean
  text: string
}

export interface NovelChapter {
  /** 1-based. */
  index: number
  title: string
  offset: number
  chars: number
}

/** `novels/chapters`. A non-empty `message` means "this text has no chapter
 *  headings" — the page says so instead of drawing an empty tree. */
export interface NovelChaptersPayload {
  name: string
  path: string
  encoding: string
  total_chars: number
  count: number
  returned: number
  truncated: boolean
  limit: number
  chapters: NovelChapter[]
  message: string
}

export interface NovelMatch {
  offset: number
  snippet: string
}

/** `novels/search`. */
export interface NovelSearchPayload {
  name: string
  path: string
  encoding: string
  total_chars: number
  query: string
  matched: number
  truncated: boolean
  limit: number
  matches: NovelMatch[]
}

/** `novels/import`. A name clash is *not* an error: it comes back as
 *  `imported: false, reason: 'exists'` so the page can ask once about
 *  overwriting. Every other failure is a rejected RPC. */
export interface NovelImportPayload {
  imported: boolean
  /** `'exists'` on a clash, `''` on success. Only two values exist. */
  reason: string
  name: string
  path: string
  bytes: number
  source: string
  overwritten: boolean
  created_dir: boolean
  message: string
}

export interface NovelDeletePayload {
  name: string
  path: string
  bytes: number
  deleted: boolean
}

/** Host bounds, mirrored 1:1 from `server.py` so the page can clamp its own
 *  inputs instead of buying an INVALID_PARAMS round-trip for a typo. */
export const NOVEL_LIST_LIMIT = 500
export const NOVEL_READ_CHARS = 4000
export const NOVEL_MAX_READ_CHARS = 40000
export const NOVEL_CHAPTER_LIMIT = 5000
export const NOVEL_SEARCH_LIMIT = 200

/** Which chapter a reader offset falls in, or -1 when there are none.
 *
 * Chapters are contiguous by construction (each one runs to the next one's
 * offset), so a linear scan from the end is both correct and cheap: the page
 * calls this once per render, not per character.
 */
export function chapterIndexAt(chapters: readonly NovelChapter[], offset: number): number {
  let found = -1
  for (let index = 0; index < chapters.length; index += 1) {
    const chapter = chapters[index]
    if (chapter && chapter.offset <= offset) found = index
    else break
  }
  return found
}

/** Human byte size. Deliberately binary (KiB) — this is a file listing, and
 *  the host reports `st_size`. */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`
}
