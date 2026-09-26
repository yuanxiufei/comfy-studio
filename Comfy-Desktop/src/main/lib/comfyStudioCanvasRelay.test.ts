import { describe, expect, it, vi } from 'vitest'
import {
  askCanvasPage,
  canvasCallScript,
  isCanvasCall,
  relayCanvasCall
} from './comfyStudioCanvasRelay'
import type { CanvasPage } from './comfyStudioCanvasRelay'

const page = (answer: unknown, overrides: Partial<CanvasPage> = {}): CanvasPage => ({
  isDestroyed: () => false,
  executeJavaScript: vi.fn(() => Promise.resolve(answer)),
  ...overrides
})

describe('canvasCallScript', () => {
  it('guards on the injected panel and forwards op + args', () => {
    const script = canvasCallScript('load_workflow', { graph: { nodes: [] }, name: 'x' })
    expect(script).toContain('window.__comfyStudioChat')
    expect(script).toContain('canvasCall')
    expect(script).toContain('"load_workflow"')
    expect(script).toContain('"graph":{"nodes":[]}')
    expect(() => new Function(script)).not.toThrow()
  })

  it('sends an empty object when the host passes no args', () => {
    expect(canvasCallScript('snapshot', undefined)).toContain('"snapshot", {}')
  })
})

describe('askCanvasPage', () => {
  it('runs the op in the page and returns its answer', async () => {
    const target = page({ ok: true, result: { node_count: 2 } })
    await expect(askCanvasPage(target, 'snapshot', {})).resolves.toEqual({
      ok: true,
      result: { node_count: 2 }
    })
    expect(target.executeJavaScript).toHaveBeenCalledTimes(1)
  })

  it('says so when there is no live window', async () => {
    await expect(askCanvasPage(null, 'snapshot', {})).resolves.toMatchObject({ ok: false })
    await expect(
      askCanvasPage(page(null, { isDestroyed: () => true }), 'snapshot', {})
    ).resolves.toMatchObject({ ok: false, error: expect.stringContaining('没开') })
  })

  it('turns an executeJavaScript failure into an answer', async () => {
    const target = page(null, {
      executeJavaScript: vi.fn(() => Promise.reject(new Error('页面没了')))
    })
    await expect(askCanvasPage(target, 'snapshot', {})).resolves.toEqual({
      ok: false,
      error: '画布动作没能执行：页面没了'
    })
  })

  it('refuses a page that answered with something else', async () => {
    await expect(askCanvasPage(page('nope'), 'snapshot', {})).resolves.toMatchObject({
      ok: false,
      error: expect.stringContaining('没有回话')
    })
  })
})

describe('relayCanvasCall', () => {
  it('hands the page answer back to the host', async () => {
    const request = vi.fn(() => Promise.resolve({ call_id: 'canvas-1', delivered: true }))
    const result = await relayCanvasCall(
      { request },
      page({ ok: true, result: { node_count: 2 } }),
      { call_id: 'canvas-1', op: 'snapshot', args: {} }
    )

    expect(request).toHaveBeenCalledWith('agent/canvas_result', {
      call_id: 'canvas-1',
      ok: true,
      result: { node_count: 2 },
      error: null
    })
    expect(result.delivered).toBe(true)
    expect(result.answer.ok).toBe(true)
  })

  it('reports an undelivered answer without throwing', async () => {
    const result = await relayCanvasCall(
      { request: vi.fn(() => Promise.resolve({ delivered: false })) },
      page({ ok: true, result: {} }),
      { call_id: 'canvas-2', op: 'snapshot' }
    )
    expect(result.delivered).toBe(false)
  })

  it('survives a host that already went away', async () => {
    const request = vi.fn(() => Promise.reject(new Error('宿主已退出')))
    await expect(
      relayCanvasCall({ request }, page({ ok: true, result: {} }), {
        call_id: 'canvas-3',
        op: 'snapshot'
      })
    ).resolves.toMatchObject({ delivered: false, answer: { ok: true } })
  })

  it('does not bother the page when the call is malformed', async () => {
    const target = page({ ok: true, result: {} })
    const request = vi.fn()
    const result = await relayCanvasCall({ request }, target, { op: 'snapshot' })
    expect(result.delivered).toBe(false)
    expect(target.executeJavaScript).not.toHaveBeenCalled()
    expect(request).not.toHaveBeenCalled()
  })

  it('passes a page failure through as ok:false', async () => {
    const request = vi.fn(() => Promise.resolve({ delivered: true }))
    await relayCanvasCall({ request }, null, { call_id: 'canvas-4', op: 'snapshot' })
    expect(request).toHaveBeenCalledWith(
      'agent/canvas_result',
      expect.objectContaining({ ok: false, error: expect.stringContaining('没开') })
    )
  })
})

describe('isCanvasCall', () => {
  it('recognises a canvas notification and nothing else', () => {
    expect(isCanvasCall('agent/event', { type: 'canvas_call' })).toBe(true)
    expect(isCanvasCall('agent/event', { type: 'tool_call' })).toBe(false)
    expect(isCanvasCall('agent/progress', { type: 'canvas_call' })).toBe(false)
  })
})
