import { describe, expect, it } from 'vitest'
import type { SkillParam } from './capabilities'
import {
  collectParams,
  mediaKind,
  paramKind,
  parseDuration,
  prefillParams,
  renderKey,
  renderRunRequest,
  runMedia,
  runNotes,
  runOutcome,
  runSaved,
  skillKey,
  splitImagePaths,
  type RenderRunPayload,
  type SkillRunPayload
} from './runs'

function param(overrides: Partial<SkillParam> & { name: string }): SkillParam {
  return {
    type: 'string',
    required: false,
    description: '',
    default: null,
    hasDefault: false,
    ...overrides
  }
}

describe('paramKind', () => {
  it('reads the engine spellings of a number as a number', () => {
    // The engine's own types are `integer` / `float` as often as `number`, and a
    // form that only knew `number` would send a numeric parameter as text.
    for (const type of ['number', 'integer', 'int', 'float', 'Number', ' INTEGER ']) {
      expect(paramKind(type)).toBe('number')
    }
  })

  it('recognises booleans and treats everything else as text', () => {
    expect(paramKind('boolean')).toBe('boolean')
    expect(paramKind('bool')).toBe('boolean')
    expect(paramKind('string')).toBe('text')
    expect(paramKind('image')).toBe('text')
    expect(paramKind('')).toBe('text')
  })
})

describe('prefillParams', () => {
  it('seeds the fields the catalog declares defaults for', () => {
    const params = [
      param({ name: 'prompt', default: 'a cat', hasDefault: true }),
      param({ name: 'seed', type: 'integer', default: 42, hasDefault: true }),
      param({ name: 'flag', type: 'boolean', default: false, hasDefault: true }),
      param({ name: 'empty', default: null, hasDefault: true }),
      param({ name: 'nope' })
    ]
    expect(prefillParams(params)).toEqual({ prompt: 'a cat', seed: '42', flag: 'false' })
  })

  it('leaves a declared null default blank, because there is no text for it', () => {
    // `hasDefault` with a null default is the host saying "the default *is* null",
    // which is not the string "null".
    expect(prefillParams([param({ name: 'x', default: null, hasDefault: true })])).toEqual({})
  })

  it('drops object defaults rather than stringifying them into the field', () => {
    // A struct has no text field to live in; omitting it sends the request
    // without the key, which is how the engine applies its own default anyway.
    expect(prefillParams([param({ name: 'x', default: { a: 1 }, hasDefault: true })])).toEqual({})
    expect(prefillParams([param({ name: 'x', default: [1, 2], hasDefault: true })])).toEqual({})
  })
})

describe('collectParams', () => {
  it('omits blank fields so the engine applies its own default', () => {
    const params = [param({ name: 'seed', default: 7, hasDefault: true })]
    const collected = collectParams(params, { seed: '' })
    expect(collected.values).toEqual({})
    expect(collected.missing).toEqual([])
    expect(collected.invalid).toEqual([])
  })

  it('blocks a required parameter that has no default, and only that', () => {
    const params = [
      param({ name: 'prompt', required: true }),
      param({ name: 'seed', required: true, hasDefault: true }),
      param({ name: 'style', required: false })
    ]
    const collected = collectParams(params, { prompt: '  ', seed: '', style: '' })
    expect(collected.missing).toEqual(['prompt'])
  })

  it('converts by declared type', () => {
    const params = [
      param({ name: 'seed', type: 'integer' }),
      param({ name: 'scale', type: 'float' }),
      param({ name: 'flag', type: 'boolean' }),
      param({ name: 'prompt' })
    ]
    const collected = collectParams(params, {
      seed: '42',
      scale: '1.5',
      flag: 'true',
      prompt: '  a cat  '
    })
    expect(collected.values).toEqual({ seed: 42, scale: 1.5, flag: true, prompt: 'a cat' })
  })

  it('reads a false boolean as false rather than as a missing value', () => {
    // The whole point of the boolean control: `false` must travel, since an
    // omitted boolean is the engine's default and defaults are usually true.
    const collected = collectParams([param({ name: 'flag', type: 'boolean' })], { flag: 'false' })
    expect(collected.values).toEqual({ flag: false })
  })

  it('refuses a number that is not one, instead of letting the engine error', () => {
    const collected = collectParams([param({ name: 'seed', type: 'integer' })], { seed: 'abc' })
    expect(collected.invalid).toEqual(['seed'])
    expect(collected.values).toEqual({})
  })

  it('reports nothing for a skill with no parameters at all', () => {
    expect(collectParams([], {})).toEqual({ values: {}, missing: [], invalid: [] })
  })
})

describe('parseDuration', () => {
  it('treats blank as "use the workflow length" rather than as zero', () => {
    expect(parseDuration('')).toEqual({ ok: true, value: null })
    expect(parseDuration('   ')).toEqual({ ok: true, value: null })
  })

  it('accepts a number and rejects anything else', () => {
    expect(parseDuration('5')).toEqual({ ok: true, value: 5 })
    expect(parseDuration(' 2.5 ')).toEqual({ ok: true, value: 2.5 })
    expect(parseDuration('five').ok).toBe(false)
    expect(parseDuration('Infinity').ok).toBe(false)
  })
})

describe('splitImagePaths', () => {
  it('splits on newlines and semicolons and drops the blanks', () => {
    expect(splitImagePaths('a.png\nb.png')).toEqual(['a.png', 'b.png'])
    expect(splitImagePaths('a.png; b.png')).toEqual(['a.png', 'b.png'])
    expect(splitImagePaths('a.png\n\n  \nb.png')).toEqual(['a.png', 'b.png'])
    expect(splitImagePaths('')).toEqual([])
  })
})

describe('mediaKind', () => {
  it('tells the three families apart by suffix', () => {
    expect(mediaKind('out/00001.png')).toBe('image')
    expect(mediaKind('out/00001.WEBP')).toBe('image')
    expect(mediaKind('out/clip.mp4')).toBe('video')
    expect(mediaKind('out/clip.webm')).toBe('video')
    expect(mediaKind('out/voice.wav')).toBe('audio')
  })

  it('returns null — not "other" — when the suffix says nothing', () => {
    // Null is what lets the caller fall back a second time; "other" would end
    // the search at the first name it could not read.
    expect(mediaKind('out/thing.bin')).toBeNull()
    expect(mediaKind('out/noextension')).toBeNull()
    expect(mediaKind('')).toBeNull()
    expect(mediaKind('http://host/view?filename=a.png&type=output')).toBeNull()
  })

  it('ignores a query string when picking the suffix out of a URL', () => {
    expect(mediaKind('http://host/a.png?x=1')).toBe('image')
  })
})

describe('runMedia', () => {
  it('reads all three buckets, because a video is not an image', () => {
    // The engine splits `{images, videos, audios}` precisely so a SaveVideo
    // output survives; reading only `images`, as the old drawer did, hides
    // every video this studio makes.
    const media = runMedia({
      images: [{ url: 'http://host/view?a', filename: 'a.png', node: '9' }],
      videos: [{ url: 'http://host/view?b', filename: 'b.mp4' }],
      audios: [{ url: 'http://host/view?c', filename: 'c.wav' }]
    })
    expect(media.map((item) => item.kind)).toEqual(['image', 'video', 'audio'])
    expect(media.map((item) => item.filename)).toEqual(['a.png', 'b.mp4', 'c.wav'])
    expect(media[0].node).toBe('9')
  })

  it('trusts the engine label over the suffix', () => {
    // `SaveVideo` writes its file under the history's `images` key, so a name
    // ending in `.png` in that bucket is exactly what the label is there for.
    const media = runMedia({ images: [{ filename: 'frame.png', kind: 'video', url: 'http://h/v' }] })
    expect(media[0].kind).toBe('video')
  })

  it('falls back to the bucket when an entry has no usable label', () => {
    const media = runMedia({
      images: [{ url: 'http://h/v', filename: 'unknown.bin' }],
      videos: [{ url: 'http://h/v2' }]
    })
    expect(media.map((item) => item.kind)).toEqual(['image', 'video'])
  })

  it('keeps the /view url intact, query string and all', () => {
    // The url is `{base}/view?filename=…`; stripping or re-parsing it would
    // break the only thing an <img> can use.
    const url = 'http://127.0.0.1:8188/view?filename=ComfyUI_00001_.png&subfolder=&type=output'
    expect(runMedia({ images: [{ url, filename: 'ComfyUI_00001_.png' }] })[0].url).toBe(url)
  })

  it('survives a `data` that is not the shape we hoped for', () => {
    // `data` is `json.loads` of whatever the tool printed, so every level of it
    // is genuinely untyped and a bad entry must cost only its own row.
    expect(runMedia(null)).toEqual([])
    expect(runMedia({})).toEqual([])
    expect(runMedia({ images: 'nope' })).toEqual([])
    expect(runMedia({ videos: null })).toEqual([])
    expect(runMedia({ images: [null, 7, {}] })).toEqual([
      { url: '', filename: '', node: '', subfolder: '', kind: 'image' },
      { url: '', filename: '', node: '', subfolder: '', kind: 'image' },
      { url: '', filename: '', node: '', subfolder: '', kind: 'image' }
    ])
  })

  it('rejects a `kind` that is not one of the engine labels', () => {
    const media = runMedia({ images: [{ filename: 'a.png', kind: '<script>' }] })
    expect(media[0].kind).toBe('image')
  })
})

describe('runNotes and runSaved', () => {
  it('keeps strings and drops everything else', () => {
    expect(runNotes({ notes: ['duration rounded to 24 frames'] })).toEqual([
      'duration rounded to 24 frames'
    ])
    expect(runNotes({ notes: ['ok', 3, null, ''] })).toEqual(['ok'])
    expect(runNotes({})).toEqual([])
    expect(runSaved({ saved: ['D:/out/a.png'] })).toEqual(['D:/out/a.png'])
    expect(runSaved({ saved: 'nope' })).toEqual([])
  })
})

describe('runOutcome', () => {
  it('normalises a skill payload', () => {
    const payload: SkillRunPayload = {
      skill_id: 'storyboard',
      isError: false,
      text: 'done',
      data: { images: [{ url: 'http://h/view?a', filename: 'a.png' }], notes: ['n'] }
    }
    expect(runOutcome(payload)).toEqual({
      isError: false,
      text: 'done',
      media: [{ url: 'http://h/view?a', filename: 'a.png', node: '', subfolder: '', kind: 'image' }],
      notes: ['n'],
      saved: []
    })
  })

  it('reads nothing out of `data` when the engine reported a failure', () => {
    // The failing path is exactly where `data` is absent or half-built; drawing
    // artefacts from it is how a blank page happens instead of an error.
    const payload: RenderRunPayload = {
      target_id: 'workflow:txt2img',
      file: null,
      isError: true,
      text: 'model not found',
      data: { images: [{ url: 'file:///stale.png', filename: 'stale.png' }] }
    }
    expect(runOutcome(payload)).toEqual({
      isError: true,
      text: 'model not found',
      media: [],
      notes: [],
      saved: []
    })
  })

  it('tolerates a missing text field', () => {
    const payload = { skill_id: 'x', isError: false, data: null } as unknown as SkillRunPayload
    expect(runOutcome(payload).text).toBe('')
  })
})

describe('renderRunRequest', () => {
  const input = {
    params: {},
    images: '',
    durationSec: '',
    outputDir: ''
  }

  function payloadOf(
    target: { targetId?: string; file?: string },
    overrides: Partial<typeof input> = {}
  ): Record<string, unknown> {
    const built = renderRunRequest(target, { ...input, ...overrides })
    if (!built.ok) throw new Error(`refused: ${built.refusal}`)
    return built.payload
  }

  it('addresses a registered target by id and nothing else', () => {
    expect(payloadOf({ targetId: 'workflow:txt2img' })).toEqual({ target_id: 'workflow:txt2img' })
  })

  it('addresses a saved workflow by filename and nothing else', () => {
    // The host rejects both at once, so the two addressing modes must never
    // appear together even when a caller passes both.
    expect(payloadOf({ file: 'txt2img.json' })).toEqual({ file: 'txt2img.json' })
    expect(payloadOf({ targetId: 'workflow:a', file: 'a.json' })).toEqual({ target_id: 'workflow:a' })
  })

  it('omits every optional field when it is blank, rather than sending empty', () => {
    // `duration_sec` must be a number and `output_dir` a non-empty string; an
    // empty string is a protocol error, not "use the default".
    const payload = payloadOf({ targetId: 't' }, { durationSec: '  ', outputDir: ' ' })
    expect(Object.keys(payload)).toEqual(['target_id'])
  })

  it('sends the parameters, the images, the duration and the output directory', () => {
    const payload = payloadOf(
      { targetId: 't' },
      {
        params: { prompt: 'a cat' },
        images: 'a.png\nb.png',
        durationSec: '4',
        outputDir: ' D:/out '
      }
    )
    expect(payload).toEqual({
      target_id: 't',
      params: { prompt: 'a cat' },
      images: ['a.png', 'b.png'],
      duration_sec: 4,
      output_dir: 'D:/out'
    })
  })

  it('omits an empty params object, which says nothing the engine needs', () => {
    expect('params' in payloadOf({ targetId: 't' })).toBe(false)
  })

  it('omits images that are only whitespace', () => {
    expect('images' in payloadOf({ targetId: 't' }, { images: '\n\n  \n' })).toBe(false)
  })

  it('refuses a non-numeric duration without sending anything', () => {
    const built = renderRunRequest({ targetId: 't' }, { ...input, durationSec: 'four' })
    expect(built).toEqual({ ok: false, refusal: 'duration' })
  })
})

describe('run keys', () => {
  it('namespaces skills and renders so an id collision cannot share a slot', () => {
    expect(skillKey('a')).toBe('skill:a')
    expect(renderKey('a')).toBe('render:a')
    expect(skillKey('a')).not.toBe(renderKey('a'))
  })

  it('keys a workflow file by its filename, which is how it is addressed', () => {
    expect(renderKey('txt2img.json')).toBe('render:txt2img.json')
  })
})
