import { describe, expect, it } from 'vitest'
import {
  capabilityTallies,
  groupState,
  requiredParams,
  toolParamCount,
  type McpTool,
  type SkillParam
} from './capabilities'

function param(name: string, required: boolean): SkillParam {
  return { name, type: 'string', required, description: '', default: null, hasDefault: false }
}

function tool(overrides: Partial<McpTool> = {}): McpTool {
  return {
    server: 'comfy',
    name: 'render',
    qualified_name: 'comfy__render',
    description: '',
    input_schema: null,
    ...overrides
  }
}

describe('groupState', () => {
  it('is ready as soon as there is a row, note or not', () => {
    expect(groupState(null, 1)).toBe('ready')
    expect(groupState('engine not configured', 3)).toBe('ready')
  })

  it('separates "this machine has no catalog" from "the catalog is empty"', () => {
    // The host only sets `note` when the directory is missing, so an empty group
    // with a note is something to go and configure; without one it is simply empty.
    expect(groupState('No workflows directory', 0)).toBe('unconfigured')
    expect(groupState(null, 0)).toBe('empty')
    expect(groupState(undefined, 0)).toBe('empty')
    expect(groupState('', 0)).toBe('empty')
  })
})

describe('requiredParams', () => {
  it('keeps only what the user has to supply, in the host order', () => {
    const params = [param('prompt', true), param('seed', false), param('model', true)]
    expect(requiredParams(params).map((entry) => entry.name)).toEqual(['prompt', 'model'])
  })

  it('is empty for an optional-only skill, so the row renders no "Needs:" line', () => {
    expect(requiredParams([param('seed', false)])).toEqual([])
    expect(requiredParams([])).toEqual([])
  })
})

describe('toolParamCount', () => {
  it('counts the properties of a well-formed schema', () => {
    const schema = { type: 'object', properties: { prompt: {}, steps: {}, seed: {} } }
    expect(toolParamCount(tool({ input_schema: schema }))).toBe(3)
  })

  it('says zero rather than throwing on anything a server can actually send', () => {
    // `input_schema` comes from a third-party MCP server. Throwing in render
    // would blank the whole page over one bad server, so every shape below has
    // to come back as a number.
    for (const schema of [
      null,
      undefined,
      'nope',
      42,
      [],
      ['a'],
      {},
      { properties: null },
      { properties: 'nope' },
      { properties: ['a', 'b'] },
      { properties: 7 }
    ]) {
      expect(toolParamCount(tool({ input_schema: schema }))).toBe(0)
    }
  })

  it('does not count nested object keys as parameters', () => {
    const schema = { properties: { options: { type: 'object', properties: { a: {}, b: {} } } } }
    expect(toolParamCount(tool({ input_schema: schema }))).toBe(1)
  })
})

describe('capabilityTallies', () => {
  it('adds the four groups up, and totals them', () => {
    const tallies = capabilityTallies({
      skills: [1, 2, 3].map(() => ({ id: '', title: '', description: '', tags: [], params: [] })),
      targets: [],
      workflows: [
        { file: 'a.json', bytes: 1, modified: '', digest: '', usedBy: [] },
        { file: 'b.json', bytes: 1, modified: '', digest: '', usedBy: [] }
      ],
      tools: [tool()]
    })
    expect(tallies).toEqual({ skills: 3, targets: 0, workflows: 2, tools: 1, total: 6 })
  })

  it('is all zeroes for a machine with nothing wired up', () => {
    expect(
      capabilityTallies({ skills: [], targets: [], workflows: [], tools: [] })
    ).toEqual({ skills: 0, targets: 0, workflows: 0, tools: 0, total: 0 })
  })

  it('totals exactly the rows the groups will render', () => {
    const tallies = capabilityTallies({
      skills: [{ id: 'a', title: '', description: '', tags: [], params: [] }],
      targets: [],
      workflows: [],
      tools: [tool(), tool()]
    })
    expect(tallies.total).toBe(tallies.skills + tallies.targets + tallies.workflows + tallies.tools)
  })
})
