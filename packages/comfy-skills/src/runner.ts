import { ComfyClient } from 'comfy-sdk'
import type { PromptProgress, PromptWorkflow } from 'comfy-sdk'
import type { Skill, SkillRunResult } from './types'
import { mergeParams } from './params'

/**
 * skill 约定：名为 seed 的参数传 -1 表示每次随机。
 * （KSampler 的 seed 上限是 0xffffffffffffffff，这里用 48 位随机避免 JSON 精度问题。）
 */
export const SEED_RANDOM = -1

export { mergeParams }

/** 生成提交给 ComfyUI 的 API 格式工作流（深拷贝，不改动模板）。 */
export function buildPrompt(skill: Skill, params: Record<string, unknown>): PromptWorkflow {
  const merged = mergeParams(skill, params)
  const prompt = JSON.parse(JSON.stringify(skill.workflow)) as PromptWorkflow
  for (const p of skill.params) {
    if (!(p.name in merged)) continue
    let v = merged[p.name]
    if (p.name === 'seed' && v === SEED_RANDOM) {
      v = Math.floor(Math.random() * 0x1_0000_0000_0000)
    }
    prompt[p.node].inputs[p.field] = v
  }
  return prompt
}

/** 校验参数并注入 skill 工作流，排队执行并等到完成。 */
export async function runSkill(
  client: ComfyClient,
  skill: Skill,
  params: Record<string, unknown>,
  onProgress?: (p: PromptProgress) => void,
): Promise<SkillRunResult> {
  const prompt = buildPrompt(skill, params)
  const { prompt_id } = await client.queuePrompt(prompt)
  const entry = await client.waitForPrompt(prompt_id, onProgress)
  const images: SkillRunResult['images'] = []
  for (const [nodeId, output] of Object.entries(entry.outputs ?? {})) {
    for (const file of output.images ?? []) {
      images.push({
        node: nodeId,
        url: client.viewUrl(file.filename, file.subfolder ?? '', file.type ?? 'output'),
        filename: file.filename,
      })
    }
  }
  return { promptId: prompt_id, images, outputs: entry.outputs ?? {} }
}
