import type { ComfyClient } from 'comfy-sdk'
import type { PromptWorkflow } from 'comfy-sdk'
import type { Skill } from 'comfy-skills'
import { runSkill } from 'comfy-skills'

export interface McpTool {
  name: string
  description: string
  inputSchema: Record<string, unknown>
  handler: (args: any) => Promise<unknown>
}

/** 每类模型用哪个节点的枚举字段探测（字段名核实自 ComfyUI nodes.py / comfy_extras）。 */
const MODEL_PROBES: Record<string, { node: string; field: string }> = {
  checkpoints: { node: 'CheckpointLoaderSimple', field: 'ckpt_name' },
  vae: { node: 'VAELoader', field: 'vae_name' },
  loras: { node: 'LoraLoader', field: 'lora_name' },
  text_encoders: { node: 'CLIPLoader', field: 'clip_name' },
  diffusion_models: { node: 'UNETLoader', field: 'unet_name' },
  controlnet: { node: 'ControlNetLoader', field: 'control_net_name' },
  upscale_models: { node: 'UpscaleModelLoader', field: 'model_name' },
}

export type ToolResult = { content: Array<{ type: 'text'; text: string }>; isError?: boolean }

export function textResult(obj: unknown): ToolResult {
  return { content: [{ type: 'text', text: typeof obj === 'string' ? obj : JSON.stringify(obj, null, 2) }] }
}

export function errorResult(err: unknown): ToolResult {
  return { content: [{ type: 'text', text: err instanceof Error ? err.message : String(err) }], isError: true }
}

function schemaFor(skill: Skill): Record<string, unknown> {
  const properties: Record<string, unknown> = {}
  const required: string[] = []
  for (const p of skill.params) {
    properties[p.name] = {
      type: p.type,
      description: p.description ?? `注入到节点 ${p.node} 的 ${p.field}`,
      ...(p.default !== undefined ? { default: p.default } : {}),
    }
    if (p.required) required.push(p.name)
  }
  return { type: 'object', properties, ...(required.length > 0 ? { required } : {}) }
}

export function buildTools(client: ComfyClient, skills: Skill[]): McpTool[] {
  const tools: McpTool[] = [
    {
      name: 'comfy_list_models',
      description: `列出本机 ComfyUI 可用的模型文件。folder 可选值: ${Object.keys(MODEL_PROBES).join(', ')}`,
      inputSchema: {
        type: 'object',
        properties: {
          folder: { type: 'string', enum: Object.keys(MODEL_PROBES), description: '模型类别，默认 checkpoints' },
        },
      },
      handler: async args => {
        const folder = args?.folder ?? 'checkpoints'
        const probe = MODEL_PROBES[folder]
        if (probe === undefined) {
          throw new Error(`未知 folder: ${String(folder)}；可选: ${Object.keys(MODEL_PROBES).join(', ')}`)
        }
        const info = await client.objectInfoNode(probe.node)
        const node = info[probe.node]
        if (node === undefined) {
          throw new Error(`节点 ${probe.node} 不存在（相关模型类型未安装？）`)
        }
        const list = node.input?.required?.[probe.field]?.[0]
        if (!Array.isArray(list)) {
          throw new Error(`无法从 ${probe.node}.${probe.field} 读取模型列表`)
        }
        return textResult(list)
      },
    },
    {
      name: 'comfy_list_skills',
      description: '列出可用的 skill（参数化工作流模板）及各自的参数定义',
      inputSchema: { type: 'object', properties: {} },
      handler: async () =>
        textResult(
          skills.map(s => ({
            id: s.id,
            title: s.title,
            description: s.description,
            tags: s.tags ?? [],
            params: s.params.map(p => ({
              name: p.name,
              type: p.type,
              required: p.required === true,
              default: p.default,
              description: p.description ?? `${p.node}.${p.field}`,
            })),
          })),
        ),
    },
    {
      name: 'comfy_run_skill',
      description: '运行一个 skill 并等待完成，返回生成的文件。参数定义先看 comfy_list_skills',
      inputSchema: {
        type: 'object',
        properties: {
          skill_id: { type: 'string', description: 'skill 的 id' },
          params: { type: 'object', description: 'skill 参数' },
        },
        required: ['skill_id'],
      },
      handler: async args => {
        const skill = skills.find(s => s.id === args?.skill_id)
        if (skill === undefined) {
          throw new Error(`没有 skill ${String(args?.skill_id)}；可用: ${skills.map(s => s.id).join(', ')}`)
        }
        const result = await runSkill(client, skill, args?.params ?? {})
        return textResult({ prompt_id: result.promptId, images: result.images })
      },
    },
    {
      name: 'comfy_submit_workflow',
      description: '直接提交一个 ComfyUI API 格式工作流（{nodeId: {class_type, inputs}}），只排队不等待，返回 prompt_id',
      inputSchema: {
        type: 'object',
        properties: {
          workflow: { type: 'object', description: 'API 格式工作流 JSON' },
        },
        required: ['workflow'],
      },
      handler: async args => {
        const workflow = args?.workflow as PromptWorkflow | undefined
        if (workflow === undefined || typeof workflow !== 'object') {
          throw new Error('缺少 workflow 参数')
        }
        return textResult(await client.queuePrompt(workflow))
      },
    },
    {
      name: 'comfy_get_history',
      description: '查询一次执行的 history 记录（含输出文件）',
      inputSchema: {
        type: 'object',
        properties: { prompt_id: { type: 'string' } },
        required: ['prompt_id'],
      },
      handler: async args => {
        if (typeof args?.prompt_id !== 'string') throw new Error('缺少 prompt_id')
        return textResult(await client.history(args.prompt_id))
      },
    },
    {
      name: 'comfy_get_queue',
      description: '查询执行队列（running / pending）',
      inputSchema: { type: 'object', properties: {} },
      handler: async () => textResult(await client.queue()),
    },
    {
      name: 'comfy_interrupt',
      description: '中断当前正在执行的任务',
      inputSchema: { type: 'object', properties: {} },
      handler: async () => {
        await client.interrupt()
        return textResult('interrupted')
      },
    },
  ]
  // 每个 skill 额外暴露成一把独立工具，Agent 直接按 schema 填参调用
  for (const skill of skills) {
    tools.push({
      name: `skill__${skill.id}`,
      description: `${skill.title} —— ${skill.description}`,
      inputSchema: schemaFor(skill),
      handler: async args => {
        const result = await runSkill(client, skill, args ?? {})
        return textResult({ prompt_id: result.promptId, images: result.images })
      },
    })
  }
  return tools
}
