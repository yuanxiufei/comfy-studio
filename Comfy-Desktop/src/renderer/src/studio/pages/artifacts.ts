/**
 * Shapes and pure helpers for the artifact shelf.
 *
 * The page is a cross-project view of exactly the data the project page shows one
 * project at a time, so the payload types are *imported* from `./projects` rather
 * than re-declared: a second copy of `ProjectSummary` would be a second thing to
 * keep in step with `lib/comfy_studio/projects.py`, and the copy that went stale
 * would not throw — it would just quietly stop matching.
 *
 * What lives here is the part the page would otherwise get wrong in several
 * places: which stages are worth showing, what order the projects go in, and the
 * tallies the header quotes. All three are decisions, and a decision made inline
 * in markup gets made again — differently — in the next branch.
 */
import type { ProjectStage, ProjectSummary } from './projects'

/** Stages that have actually left something behind, in the host's order. */
export function landedStages(summary: ProjectSummary): ProjectStage[] {
  return summary.stages.filter((stage) => stage.files > 0)
}

/**
 * Stages that have produced nothing yet, in the host's order.
 *
 * Kept separate from `landedStages` instead of being "the rest of the list" at
 * the call site: the two are rendered as different things (a row of artifacts
 * versus a single count), and a stage that is `done` but empty on disk belongs
 * with the empty ones — it has nothing to show.
 */
export function pendingStages(summary: ProjectSummary): ProjectStage[] {
  return summary.stages.filter((stage) => stage.files === 0)
}

/**
 * Projects in working order: most recently touched first.
 *
 * `mtime` leads because the shelf answers "what have I been working on"; the file
 * count breaks ties (a project with artifacts beats one with none), and the name
 * breaks the rest so the order is stable across refreshes. A JSON object's key
 * order is not a UI decision, and neither is whatever the host happened to scan
 * first.
 */
export function byActivity(projects: readonly ProjectSummary[]): ProjectSummary[] {
  return [...projects].sort(
    (a, b) => b.mtime - a.mtime || b.files - a.files || a.name.localeCompare(b.name)
  )
}

export interface ShelfTallies {
  /** Projects on the shelf. */
  projects: number
  /** How many of them have left at least one file behind. */
  started: number
  /** Files across every project. */
  files: number
  /** Required inputs that are missing, summed — the reason a stage can't run. */
  gaps: number
  /** Machine stages that have produced something, and the total to compare it to. */
  stagesDone: number
  stagesTotal: number
}

/**
 * The header's numbers, computed once.
 *
 * Both the summary band and the empty state quote these; computing them in the
 * template twice is how a header ends up saying "0 files" above a list of files.
 */
export function shelfTallies(projects: readonly ProjectSummary[]): ShelfTallies {
  const tallies: ShelfTallies = {
    projects: projects.length,
    started: 0,
    files: 0,
    gaps: 0,
    stagesDone: 0,
    stagesTotal: 0
  }
  for (const project of projects) {
    if (project.files > 0) tallies.started += 1
    tallies.files += project.files
    tallies.gaps += project.missing_count
    tallies.stagesDone += project.stages_done
    tallies.stagesTotal += project.stages_total
  }
  return tallies
}

/** How many of a landing's sample paths to show per stage row. Beyond a handful
 *  the row stops being a glance and starts being a second list to read. */
export const STAGE_SAMPLE_SHOWN = 3
