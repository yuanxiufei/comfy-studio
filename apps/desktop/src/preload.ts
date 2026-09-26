import { contextBridge, ipcRenderer } from 'electron'

export interface SkillSummary {
  id: string
  title: string
  description: string
  params: Array<{
    name: string
    type: 'string' | 'integer' | 'number' | 'boolean'
    description?: string
    required?: boolean
    default?: string | number | boolean
    node: string
    field: string
  }>
}

export interface ProgressMessage {
  skillId: string
  type: 'progress' | 'executing' | 'executed' | 'execution_cached'
  node?: string
  value?: number
  max?: number
}

contextBridge.exposeInMainWorld('studio', {
  baseUrl: (): Promise<string> => ipcRenderer.invoke('app:baseUrl'),
  listSkills: (): Promise<SkillSummary[]> => ipcRenderer.invoke('skills:list'),
  runSkill: (
    skillId: string,
    params: Record<string, unknown>,
  ): Promise<{ promptId: string; images: Array<{ node: string; url: string; filename: string }> }> =>
    ipcRenderer.invoke('skills:run', skillId, params),
  onProgress: (cb: (msg: ProgressMessage) => void): void => {
    ipcRenderer.on('skill-progress', (_e, msg: ProgressMessage) => cb(msg))
  },
})
