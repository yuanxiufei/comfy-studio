import type { NodeOutput, PromptWorkflow } from 'comfy-sdk'

export type SkillParamType = 'string' | 'integer' | 'number' | 'boolean'

export interface SkillParam {
  name: string
  type: SkillParamType
  /** 参数注入的目标：workflow 节点 id + 该节点 inputs 里的键。 */
  node: string
  field: string
  description?: string
  required?: boolean
  default?: string | number | boolean
}

/**
 * skill = 一个 ComfyUI API 格式工作流模板 + 参数表。
 * 运行时把参数值写进 workflow[node].inputs[field] 后提交执行。
 */
export interface Skill {
  id: string
  title: string
  description: string
  tags?: string[]
  workflow: PromptWorkflow
  params: SkillParam[]
}

export interface SkillOutputImage {
  node: string
  url: string
  filename: string
}

export interface SkillRunResult {
  promptId: string
  images: SkillOutputImage[]
  outputs: Record<string, NodeOutput>
}
