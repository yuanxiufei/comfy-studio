import type { Skill } from './types'

/**
 * 合并用户参数与默认值并做严格类型校验。
 * 未知参数名、缺必填参数、类型不符都直接抛错并给出可用项列表，绝不静默忽略。
 */
export function mergeParams(skill: Skill, params: Record<string, unknown>): Record<string, unknown> {
  if (params === null || typeof params !== 'object') {
    throw new Error(`skill ${skill.id} 的参数必须是对象`)
  }
  const unknownNames = Object.keys(params).filter(k => !skill.params.some(p => p.name === k))
  if (unknownNames.length > 0) {
    const valid = skill.params.map(p => p.name).join(', ') || '(无)'
    throw new Error(`skill ${skill.id} 不接受参数: ${unknownNames.join(', ')}；可用参数: ${valid}`)
  }
  const merged: Record<string, unknown> = {}
  for (const p of skill.params) {
    const v = params[p.name] ?? p.default
    if (v === undefined) {
      if (p.required) {
        throw new Error(`skill ${skill.id} 缺少必填参数 ${p.name}：${p.description ?? `${p.node}.${p.field}`}`)
      }
      continue
    }
    switch (p.type) {
      case 'string':
        if (typeof v !== 'string') throw new Error(`参数 ${p.name} 需要 string，得到 ${JSON.stringify(v)}`)
        break
      case 'integer':
        if (typeof v !== 'number' || !Number.isInteger(v)) {
          throw new Error(`参数 ${p.name} 需要 integer，得到 ${JSON.stringify(v)}`)
        }
        break
      case 'number':
        if (typeof v !== 'number') throw new Error(`参数 ${p.name} 需要 number，得到 ${JSON.stringify(v)}`)
        break
      case 'boolean':
        if (typeof v !== 'boolean') throw new Error(`参数 ${p.name} 需要 boolean，得到 ${JSON.stringify(v)}`)
        break
    }
    merged[p.name] = v
  }
  return merged
}
