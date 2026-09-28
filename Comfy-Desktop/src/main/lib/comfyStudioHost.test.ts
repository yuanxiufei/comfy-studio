import fs from 'fs'
import os from 'os'
import path from 'path'
import { afterAll, beforeEach, describe, expect, it, vi } from 'vitest'

// `bundledScript` reads `app.isPackaged` to pick the dev vs packaged layout.
vi.mock('electron', () => ({ app: { isPackaged: false } }))

// 真身 settings 在模块顶层就去算用户数据目录（configDir → electron app.getPath），
// 而这几条用例只关心它给出的 inputDir / outputDir，整份替掉，别把 Electron 拖进来。
const settingsMock = vi.hoisted(() => ({
  values: {} as Record<string, string | undefined>,
  defaults: { inputDir: '', outputDir: '' }
}))
vi.mock('../settings', () => ({
  get: (key: string) => settingsMock.values[key],
  defaults: settingsMock.defaults
}))

import {
  getBundledLibDir,
  resolveEngineStorageDirs,
  resolveStudioCommand,
  studioTimeoutForMethod,
  STUDIO_QUERY_TIMEOUT_MS,
  STUDIO_REQUEST_TIMEOUT_MS,
  STUDIO_SLOW_TIMEOUT_MS
} from './comfyStudioHost'
import { getVenvPythonPath } from './pythonEnv'
import type { InstallationRecord } from '../installations'

const SHARED_INPUT = path.join('shared-root', 'input')
const SHARED_OUTPUT = path.join('shared-root', 'output')

const tempRoots: string[] = []

/** 造一个最小可用安装：`ComfyUI/main.py` + `ComfyUI/.venv/Scripts/python.exe`。 */
function makeInstall(overrides: Record<string, unknown> = {}): InstallationRecord {
  const installPath = fs.mkdtempSync(path.join(os.tmpdir(), 'comfy-studio-host-'))
  tempRoots.push(installPath)
  const comfyuiDir = path.join(installPath, 'ComfyUI')
  fs.mkdirSync(comfyuiDir, { recursive: true })
  fs.writeFileSync(path.join(comfyuiDir, 'main.py'), '')
  const python = getVenvPythonPath(installPath)
  fs.mkdirSync(path.dirname(python), { recursive: true })
  fs.writeFileSync(python, '')
  return { id: 'test-install', installPath, ...overrides } as unknown as InstallationRecord
}

/** `--flag` 后面那个值；没有这个 flag 时回 null。 */
function argValue(args: string[], flag: string): string | null {
  const index = args.indexOf(flag)
  return index === -1 ? null : (args[index + 1] ?? null)
}

beforeEach(() => {
  settingsMock.values = {}
  settingsMock.defaults.inputDir = SHARED_INPUT
  settingsMock.defaults.outputDir = SHARED_OUTPUT
})

afterAll(() => {
  for (const root of tempRoots) fs.rmSync(root, { recursive: true, force: true })
})

describe('getBundledLibDir', () => {
  it('返回 comfy_studio 包的父目录，而不是包目录本身', () => {
    // 这个目录会被当成宿主的 cwd，也就是 `-m comfy_studio` 的 sys.path[0]。
    // 少剥一层就会得到包目录本身，于是 Python 去找
    // `<lib>/comfy_studio/comfy_studio`，报 "No module named comfy_studio"。
    expect(path.basename(getBundledLibDir())).toBe('lib')
  })
})

describe('resolveEngineStorageDirs', () => {
  it('共享开启（默认）时取全局 settings 的两个目录', () => {
    settingsMock.values = { inputDir: '/global/in', outputDir: '/global/out' }

    const dirs = resolveEngineStorageDirs(makeInstall())

    expect(dirs).toEqual({ inputDir: '/global/in', outputDir: '/global/out' })
  })

  it('settings 里没值时回落到 defaults', () => {
    const dirs = resolveEngineStorageDirs(makeInstall())

    expect(dirs).toEqual({ inputDir: SHARED_INPUT, outputDir: SHARED_OUTPUT })
  })

  it('关掉共享时改用 per-install 字段', () => {
    const dirs = resolveEngineStorageDirs(
      makeInstall({ useSharedInput: false, useSharedOutput: false, inputDir: '/own/in', outputDir: '/own/out' })
    )

    expect(dirs).toEqual({ inputDir: '/own/in', outputDir: '/own/out' })
  })

  it('关掉共享又没有 per-install 目录时给 null，让两边一起回落到 <base>/{input,output}', () => {
    // 引擎那次启动不会注入 --input-directory/--output-directory，宿主也不该硬塞一个，
    // 否则两边算出来的就不是同一个目录了。
    const dirs = resolveEngineStorageDirs(makeInstall({ useSharedInput: false, useSharedOutput: false }))

    expect(dirs).toEqual({ inputDir: null, outputDir: null })
  })

  it('input 与 output 各自独立判断', () => {
    const dirs = resolveEngineStorageDirs(
      makeInstall({ useSharedInput: true, useSharedOutput: false, outputDir: '/own/out' })
    )

    expect(dirs.inputDir).toBe(SHARED_INPUT)
    expect(dirs.outputDir).toBe('/own/out')
  })

  it('per-install 目录没有引号包着的空白时照原样返回', () => {
    const dirs = resolveEngineStorageDirs(
      makeInstall({ useSharedInput: false, inputDir: '/own/in' })
    )

    expect(dirs.inputDir).toBe('/own/in')
  })
})

describe('resolveStudioCommand', () => {
  it('把引擎真实用的 input/output 目录接给宿主', () => {
    settingsMock.values = { inputDir: '/global/in', outputDir: '/global/out' }
    const installation = makeInstall()

    const command = resolveStudioCommand(installation)!

    // 宿主侧 localfiles.py 默认按 <comfyui-dir>/input|output 找；不接这两个参数，
    // import_file 拷进去的素材引擎读不到、list_files 报的产出路径也是错的。
    expect(argValue(command.args, '--input-dir')).toBe('/global/in')
    expect(argValue(command.args, '--output-dir')).toBe('/global/out')
    expect(argValue(command.args, '--comfyui-dir')).toBe(path.join(installation.installPath, 'ComfyUI'))
    expect(command.comfyuiDir).toBe(path.join(installation.installPath, 'ComfyUI'))
  })

  it('引擎那次启动不注入目录时，这两个参数也不给', () => {
    const command = resolveStudioCommand(
      makeInstall({ useSharedInput: false, useSharedOutput: false })
    )!

    expect(command.args).not.toContain('--input-dir')
    expect(command.args).not.toContain('--output-dir')
  })
})

describe('studioTimeoutForMethod', () => {
  it('慢方法给长超时，其余一律给查询档', () => {
    // 一轮对话和一次 skill 运行的长度由**活**决定，不由"宿主还活着吗"决定；
    // 其余（agent/models、agent/agents、host/info …）在健康时是毫秒级的事，吊着不放
    // 只会让面板那排控件一直禁用 —— 开一次抽屉会同时发好几条这种请求。
    expect(studioTimeoutForMethod('agent/chat')).toBe(STUDIO_SLOW_TIMEOUT_MS)
    expect(studioTimeoutForMethod('skills/run')).toBe(STUDIO_SLOW_TIMEOUT_MS)
    expect(studioTimeoutForMethod('agent/models')).toBe(STUDIO_QUERY_TIMEOUT_MS)
    expect(studioTimeoutForMethod('agent/agents')).toBe(STUDIO_QUERY_TIMEOUT_MS)
    expect(studioTimeoutForMethod('host/info')).toBe(STUDIO_QUERY_TIMEOUT_MS)
  })

  it('长超时排在宿主自己的轮次看门狗后面', () => {
    // 这个先后不是审美问题：主进程这个超时只把本地记录删掉，**不会通知子进程**
    // （见 comfyStudioHost.request）。让它先触发 = 面板解锁了、那一轮还在背后跑；
    // 让宿主先触发 = 真的停了，而且那句错说得清是哪一步慢。
    // `--request-timeout` 传的就是 STUDIO_REQUEST_TIMEOUT_MS，宿主看门狗默认取同一个数
    //（lib/comfy_studio/server.py 的 DEFAULT_TURN_TIMEOUT）。
    expect(STUDIO_SLOW_TIMEOUT_MS).toBeGreaterThan(STUDIO_REQUEST_TIMEOUT_MS)
    expect(STUDIO_QUERY_TIMEOUT_MS).toBeLessThan(STUDIO_REQUEST_TIMEOUT_MS)
  })
})
