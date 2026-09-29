import { describe, expect, it } from 'vitest'
import {
  currentRef,
  DEFAULT_SOURCE,
  modelRef,
  pickableGroups,
  prefillSettings,
  savedSettings,
  selectableRefs,
  selectedRef,
  settingsDirty,
  settingsRequest,
  splitModelRef,
  type AgentModelsPayload,
  type AgentSettingsPayload,
  type ModelGroup,
  type SettingsForm,
  type SettingsSaved
} from './agentSetup'

function group(overrides: Partial<ModelGroup> & { source: string }): ModelGroup {
  return {
    label: overrides.source,
    models: [],
    origin: 'endpoint',
    error: null,
    ...overrides
  }
}

function modelsPayload(overrides: Partial<AgentModelsPayload> = {}): AgentModelsPayload {
  return {
    current: 'qwen2.5:7b',
    current_source: 'local',
    models: [],
    source: 'local',
    error: null,
    groups: [],
    extra_error: null,
    ...overrides
  }
}

function settingsPayload(overrides: Partial<AgentSettingsPayload> = {}): AgentSettingsPayload {
  return {
    path: 'C:/cfg/settings.json',
    exists: true,
    saved: null,
    from_file: [],
    from_env: [],
    file_error: null,
    configured: true,
    model: null,
    base_url: null,
    error: null,
    ...overrides
  }
}

describe('modelRef and splitModelRef', () => {
  it('joins source and name with the separator the host splits on', () => {
    expect(modelRef('local', 'qwen2.5:7b')).toBe('local::qwen2.5:7b')
  })

  it('falls back to the primary source when the source is empty', () => {
    expect(modelRef('', 'qwen2.5:7b')).toBe(`${DEFAULT_SOURCE}::qwen2.5:7b`)
  })

  it('round-trips a ref whose model name itself contains the separator', () => {
    // `indexOf`, not `split`: the name is everything after the *first* separator,
    // so a model named `a::b` survives the trip.
    expect(splitModelRef('local::a::b')).toEqual({ source: 'local', name: 'a::b' })
  })

  it('assumes the primary source for a ref with no separator', () => {
    // `agent/model` rejects such a ref, but an older host's bare model name must
    // still land somewhere selectable rather than produce an empty dropdown.
    expect(splitModelRef('qwen2.5:7b')).toEqual({ source: DEFAULT_SOURCE, name: 'qwen2.5:7b' })
    expect(splitModelRef('')).toEqual({ source: DEFAULT_SOURCE, name: '' })
  })
})

describe('currentRef', () => {
  it('qualifies the host model with its source', () => {
    expect(currentRef(modelsPayload())).toBe('local::qwen2.5:7b')
  })

  it('is null when the host has no model in effect', () => {
    expect(currentRef(modelsPayload({ current: null }))).toBeNull()
    expect(currentRef(null)).toBeNull()
  })
})

describe('pickableGroups', () => {
  it('keeps groups with models and groups that failed', () => {
    const payload = modelsPayload({
      groups: [
        group({ source: 'local', models: ['a'] }),
        group({ source: 'broken', error: 'connection refused' }),
        group({ source: 'empty' })
      ]
    })
    expect(pickableGroups(payload).map((entry) => entry.source)).toEqual(['local', 'broken'])
  })

  it('is empty for a payload that never arrived', () => {
    expect(pickableGroups(null)).toEqual([])
  })
})

describe('selectableRefs', () => {
  it('lists every model, qualified, in host order', () => {
    const payload = modelsPayload({
      groups: [
        group({ source: 'local', models: ['a', 'b'] }),
        group({ source: 'remote', models: ['c'] })
      ]
    })
    expect(selectableRefs(payload)).toEqual(['local::a', 'local::b', 'remote::c'])
  })
})

describe('selectedRef', () => {
  it('picks the current model when a group lists it', () => {
    const payload = modelsPayload({
      current: 'a',
      current_source: 'local',
      groups: [group({ source: 'local', models: ['a', 'b'] })]
    })
    expect(selectedRef(payload)).toBe('local::a')
  })

  it('keeps an unlisted current model selectable', () => {
    // A deleted alias, or a source whose `/models` call failed: falling back to
    // the first entry would make the dropdown claim a different model is in use.
    const payload = modelsPayload({
      current: 'gone',
      current_source: 'local',
      groups: [group({ source: 'local', models: ['a'] })]
    })
    expect(selectedRef(payload)).toBe('local::gone')
  })

  it('falls back to the first model only when the host has none', () => {
    const payload = modelsPayload({
      current: null,
      groups: [group({ source: 'local', models: ['a', 'b'] })]
    })
    expect(selectedRef(payload)).toBe('local::a')
  })

  it('is null with nothing to show at all', () => {
    expect(selectedRef(modelsPayload({ current: null }))).toBeNull()
    expect(selectedRef(null)).toBeNull()
  })
})

describe('savedSettings', () => {
  it('returns the file contents a read reports', () => {
    const saved: SettingsSaved = { model: 'a', base_url: 'http://x', has_key: true, extra_sources: [] }
    const payload = settingsPayload({ saved })
    expect(savedSettings(payload)).toEqual(saved)
  })

  it('returns null after a write, because the host overwrites `saved` with `true`', () => {
    // This is the trap the type exists for: `agent/settings` writes
    // `{"saved": true}` over the same key a read fills with the file's contents.
    expect(savedSettings(settingsPayload({ saved: true }))).toBeNull()
    expect(savedSettings(settingsPayload({ saved: null }))).toBeNull()
  })
})

describe('prefillSettings', () => {
  it('prefers the effective values, which is what an environment override changes', () => {
    const payload = settingsPayload({
      model: 'from-env',
      base_url: 'http://env',
      saved: { model: 'from-file', base_url: 'http://file', has_key: false, extra_sources: [] }
    })
    expect(prefillSettings(payload)).toEqual({ model: 'from-env', baseUrl: 'http://env' })
  })

  it('falls back to the file when the effective value is absent', () => {
    const payload = settingsPayload({
      saved: { model: 'from-file', base_url: 'http://file', has_key: false, extra_sources: [] }
    })
    expect(prefillSettings(payload)).toEqual({ model: 'from-file', baseUrl: 'http://file' })
  })

  it('is blank before the first read, never `null` in a text field', () => {
    expect(prefillSettings(null)).toEqual({ model: '', baseUrl: '' })
    expect(prefillSettings(settingsPayload())).toEqual({ model: '', baseUrl: '' })
  })

  it('never pre-fills the key, which the host does not send back', () => {
    const payload = settingsPayload({ model: 'a', saved: true })
    expect(Object.keys(prefillSettings(payload))).toEqual(['model', 'baseUrl'])
  })
})

function form(overrides: Partial<SettingsForm> = {}): SettingsForm {
  return { model: '', baseUrl: '', apiKey: '', clearKey: false, ...overrides }
}

describe('settingsRequest', () => {
  it('always sends the model and the address, trimmed', () => {
    expect(settingsRequest(form({ model: ' a ', baseUrl: ' http://x ' }))).toEqual({
      COMFY_STUDIO_LLM_MODEL: 'a',
      COMFY_STUDIO_LLM_BASE_URL: 'http://x'
    })
  })

  it('omits the key when the field is untouched, so a save cannot wipe it', () => {
    // The key is never pre-filled (only `has_key` comes back), so an empty field
    // has to mean "leave it alone" — sending `""` would delete it on every save.
    const payload = settingsRequest(form({ model: 'a' }))
    expect('COMFY_STUDIO_LLM_API_KEY' in payload).toBe(false)
  })

  it('sends a new key when one is typed', () => {
    const payload = settingsRequest(form({ apiKey: ' sk-1 ' }))
    expect(payload.COMFY_STUDIO_LLM_API_KEY).toBe('sk-1')
  })

  it('sends an empty key only for the explicit clear', () => {
    // The host reads `""` as "drop this setting", which is the only delete path.
    const payload = settingsRequest(form({ clearKey: true, apiKey: '' }))
    expect(payload.COMFY_STUDIO_LLM_API_KEY).toBe('')
    expect(settingsDirty(form({ clearKey: true }))).toBe(true)
  })

  it('ignores a typed key when the clear toggle is on', () => {
    const payload = settingsRequest(form({ apiKey: 'sk-1', clearKey: true }))
    expect(payload.COMFY_STUDIO_LLM_API_KEY).toBe('')
  })
})

describe('settingsDirty', () => {
  it('is false for an empty form, because the host answers an empty write with a read', () => {
    expect(settingsDirty(form())).toBe(false)
    expect(settingsDirty(form({ model: '  ', baseUrl: ' ', apiKey: ' ' }))).toBe(false)
  })

  it('is true as soon as any field has something in it', () => {
    expect(settingsDirty(form({ model: 'a' }))).toBe(true)
    expect(settingsDirty(form({ baseUrl: 'http://x' }))).toBe(true)
    expect(settingsDirty(form({ apiKey: 'k' }))).toBe(true)
  })
})
