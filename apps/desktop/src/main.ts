import { spawn, type ChildProcess } from 'node:child_process'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import { app, BrowserWindow, dialog, ipcMain, Menu, Tray } from 'electron'
import { ComfyClient } from 'comfy-sdk'
import { loadSkills, runSkill } from 'comfy-skills'
import type { Skill } from 'comfy-skills'

interface DesktopConfig {
  /** ComfyUI 服务地址。 */
  comfyUrl: string
  /**
   * ComfyUI 仓库路径。设置且 comfyUrl 不可达时由桌面端拉起后端进程；
   * 为 null 时只连接已运行的服务，连不上直接报错。
   */
  comfyuiDir: string | null
  pythonCmd: string
}

const require_ = createRequire(__filename)

let config: DesktopConfig
let client: ComfyClient
let skills: Skill[]
let backend: ChildProcess | null = null
let mainWindow: BrowserWindow | null = null
let tray: Tray | null = null

function configPath(): string {
  return join(app.getPath('userData'), 'config.json')
}

function defaultConfig(): DesktopConfig {
  return {
    comfyUrl: 'http://127.0.0.1:8188',
    comfyuiDir: null,
    pythonCmd: 'python',
  }
}

function loadConfig(): DesktopConfig {
  const p = configPath()
  if (!existsSync(p)) {
    const initial = defaultConfig()
    writeFileSync(p, JSON.stringify(initial, null, 2))
    return initial
  }
  return JSON.parse(readFileSync(p, 'utf8')) as DesktopConfig
}

function skillsDir(): string {
  if (process.env.COMFY_SKILLS_DIR !== undefined) return process.env.COMFY_SKILLS_DIR
  const pkg = require_.resolve('comfy-skills/package.json')
  return join(dirname(pkg), 'skills')
}

async function serverUp(url: string, timeoutMs = 1500): Promise<boolean> {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(timeoutMs) })
    return res.ok
  } catch {
    return false
  }
}

async function startBackendIfNeeded(): Promise<void> {
  if (await serverUp(config.comfyUrl)) return
  if (config.comfyuiDir === null || config.comfyuiDir === '') {
    throw new Error(
      `没有正在运行的 ComfyUI（${config.comfyUrl}），且 config.json 未设置 comfyuiDir，无法自动拉起。\n` +
        `请先启动 ComfyUI，或把 comfyuiDir 填成本地仓库路径：${configPath()}`,
    )
  }
  const port = new URL(config.comfyUrl).port || '8188'
  backend = spawn(
    config.pythonCmd,
    [join(config.comfyuiDir, 'main.py'), '--port', port],
    { cwd: config.comfyuiDir, stdio: ['ignore', 'pipe', 'pipe'] },
  )
  backend.stdout?.on('data', d => process.stdout.write(`[comfyui] ${d}`))
  backend.stderr?.on('data', d => process.stderr.write(`[comfyui] ${d}`))
  await client.waitUntilHealthy(300_000, 1000)
}

function createMainWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1600,
    height: 1000,
    title: 'Comfy Studio',
  })
  mainWindow.removeMenu()
  mainWindow.loadURL(config.comfyUrl)
  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

function createSkillPanel(): void {
  const win = new BrowserWindow({
    width: 900,
    height: 700,
    title: 'Skill 面板',
    webPreferences: {
      preload: join(__dirname, 'preload.js'),
    },
  })
  win.removeMenu()
  win.loadFile(join(__dirname, '../panel/index.html'))
}

function createTray(): void {
  // Windows 上 Tray 必须有 icon；项目未内置图标，直接跳过（不装死路径）
  const iconPath = join(__dirname, '../panel/icon.png')
  if (!existsSync(iconPath)) return
  tray = new Tray(iconPath)
  tray.setToolTip('Comfy Studio')
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: '显示主窗口', click: () => mainWindow?.show() },
      { label: 'Skill 面板', click: () => createSkillPanel() },
      { type: 'separator' },
      {
        label: '退出',
        click: () => {
          backend?.kill()
          app.quit()
        },
      },
    ]),
  )
  tray.on('click', () => mainWindow?.show())
}

function registerIpc(): void {
  ipcMain.handle('app:baseUrl', () => client.baseUrl)

  ipcMain.handle('skills:list', () =>
    skills.map(s => ({ id: s.id, title: s.title, description: s.description, params: s.params })),
  )

  ipcMain.handle('skills:run', async (_e, skillId: string, params: Record<string, unknown>) => {
    const skill = skills.find(s => s.id === skillId)
    if (skill === undefined) {
      throw new Error(`没有 skill ${String(skillId)}；可用: ${skills.map(s => s.id).join(', ')}`)
    }
    return runSkill(client, skill, params ?? {}, p => {
      for (const win of BrowserWindow.getAllWindows()) {
        win.webContents.send('skill-progress', { skillId, ...p })
      }
    })
  })
}

async function bootstrap(): Promise<void> {
  config = loadConfig()
  client = new ComfyClient(config.comfyUrl)
  skills = loadSkills(skillsDir())
  await startBackendIfNeeded()
  createMainWindow()
  createTray()
  registerIpc()
  Menu.setApplicationMenu(
    Menu.buildFromTemplate([
      {
        label: '查看',
        submenu: [
          { role: 'reload' },
          { role: 'forceReload' },
          { role: 'toggleDevTools' },
          { type: 'separator' },
          { label: 'Skill 面板', click: () => createSkillPanel() },
        ],
      },
      {
        label: '编辑',
        submenu: [
          { role: 'copy' },
          { role: 'paste' },
          { role: 'selectAll' },
        ],
      },
    ]),
  )
}

app.whenReady().then(() => {
  bootstrap().catch(err => {
    const message = err instanceof Error ? err.message : String(err)
    dialog.showErrorBox('Comfy Studio 启动失败', message)
    app.quit()
  })
})

app.on('window-all-closed', () => {
  backend?.kill()
  app.quit()
})
