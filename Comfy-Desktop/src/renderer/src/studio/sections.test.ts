import { describe, expect, it } from 'vitest'
import {
  DEFAULT_SECTION,
  STUDIO_SECTIONS,
  allPageIds,
  isStudioSectionId,
  pagesOf,
  sectionOfPage
} from './sections'

describe('studio sections', () => {
  it('covers every page id exactly once', () => {
    const ids = allPageIds()
    expect(ids.length).toBeGreaterThan(0)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('drives the nav and the page grids from the same list', () => {
    for (const section of STUDIO_SECTIONS) {
      expect(pagesOf(section.id)).toEqual(section.pages)
      expect(section.pages.length).toBeGreaterThan(0)
    }
    // Every section id resolves, so a nav item can never be dead.
    expect(STUDIO_SECTIONS.map((s) => s.id)).toContain(DEFAULT_SECTION)
  })

  it('labels every section and page through i18n keys', () => {
    for (const section of STUDIO_SECTIONS) {
      expect(section.labelKey).toMatch(/^studio\.section\./)
      for (const page of section.pages) {
        expect(page.labelKey).toMatch(/^studio\.pages\./)
      }
    }
  })

  it('declares whether each page is backed by a component', () => {
    for (const section of STUDIO_SECTIONS) {
      for (const page of section.pages) {
        expect(typeof page.built, `${page.id} must state its build state`).toBe('boolean')
      }
    }
    expect(STUDIO_SECTIONS.flatMap((s) => s.pages).some((p) => p.built)).toBe(true)
  })

  it('has no page left advertising a milestone it no longer needs', () => {
    // P4 is the last milestone, so every page the plan declares is now backed by
    // a component. The failure this guards is the quiet one: a page gets built,
    // `built` is not flipped, and the shell keeps offering it a "coming later"
    // card next to the real thing.
    const unbuilt = STUDIO_SECTIONS.flatMap((s) => s.pages)
      .filter((page) => !page.built)
      .map((page) => `${page.id} (${page.milestone})`)
    expect(unbuilt).toEqual([])
  })

  it('rejects unknown section ids instead of falling through', () => {
    expect(isStudioSectionId('drama')).toBe(true)
    expect(isStudioSectionId('workbench')).toBe(false)
    expect(isStudioSectionId(undefined)).toBe(false)
    expect(isStudioSectionId({ id: 'drama' })).toBe(false)
  })

  it('maps a page back to its owning section (host-driven view hints)', () => {
    expect(sectionOfPage('novel')).toBe('drama')
    expect(sectionOfPage('journal')).toBe('assets')
  })
})
