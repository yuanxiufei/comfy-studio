import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import type { Skill, SkillParam, SkillParamType } from './types'

const PARAM_TYPES = new Set<SkillParamType>(['string', 'integer', 'number', 'boolean'])

/** 读取目录下全部 skill 文件（按文件名排序）。任何文件不合法直接抛错，不做静默跳过。 */
export function loadSkills(dir: string): Skill[] {
  const files = readdirSync(dir)
    .filter(f => f.endsWith('.json'))
    .sort()
  if (files.length === 0) {
    throw new Error(`skill 目录 ${dir} 里没有任何 .json 文件`)
  }
  return files.map(f => loadSkillFile(join(dir, f)))
}

export function loadSkillFile(path: string): Skill {
  let raw: unknown
  try {
    raw = JSON.parse(readFileSync(path, 'utf8'))
  } catch (err) {
    throw new Error(`skill 文件 ${path} 不是合法 JSON: ${err instanceof Error ? err.message : String(err)}`)
  }
  return validateSkill(raw, path)
}

export function validateSkill(raw: unknown, source: string): Skill {
  if (typeof raw !== 'object' || raw === null) {
    throw new Error(`${source}: skill 必须是 JSON 对象`)
  }
  const s = raw as Record<string, unknown>
  for (const key of ['id', 'title', 'description'] as const) {
    if (typeof s[key] !== 'string' || (s[key] as string) === '') {
      throw new Error(`${source}: ${key} 必须是非空字符串`)
    }
  }
  if (typeof s.workflow !== 'object' || s.workflow === null) {
    throw new Error(`${source}: workflow 必须是节点映射（ComfyUI API 格式）`)
  }
  const workflow = s.workflow as Record<string, { class_type: unknown; inputs: Record<string, unknown> }>
  for (const [nodeId, node] of Object.entries(workflow)) {
    if (
      typeof node !== 'object' || node === null ||
      typeof node.class_type !== 'string' ||
      typeof node.inputs !== 'object' || node.inputs === null
    ) {
      throw new Error(`${source}: workflow 节点 ${nodeId} 缺少 class_type 或 inputs`)
    }
  }
  if (!Array.isArray(s.params)) {
    throw new Error(`${source}: params 必须是数组`)
  }
  const seen = new Set<string>()
  for (const p of s.params as unknown[]) {
    const param = p as Partial<SkillParam>
    if (typeof param.name !== 'string' || param.name === '') {
      throw new Error(`${source}: 每个参数必须有非空 name`)
    }
    if (seen.has(param.name)) {
      throw new Error(`${source}: 参数 ${param.name} 重复定义`)
    }
    seen.add(param.name)
    if (param.type === undefined || !PARAM_TYPES.has(param.type)) {
      throw new Error(`${source}: 参数 ${param.name} 的 type 必须是 ${[...PARAM_TYPES].join('/')}`)
    }
    if (typeof param.node !== 'string' || !(param.node in workflow)) {
      throw new Error(
        `${source}: 参数 ${param.name} 引用的节点 ${String(param.node)} 不在 workflow 里（可用节点: ${Object.keys(workflow).join(', ')}）`,
      )
    }
    if (typeof param.field !== 'string' || param.field === '') {
      throw new Error(`${source}: 参数 ${param.name} 缺少 field`)
    }
    const inputs = workflow[param.node].inputs
    if (!(param.field in inputs)) {
      throw new Error(
        `${source}: 参数 ${param.name} 的字段 ${param.field} 不是节点 ${param.node} 的输入（可用: ${Object.keys(inputs).join(', ')}）`,
      )
    }
  }
  return raw as Skill
}
