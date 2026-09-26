// 类型对照 ComfyUI server.py / execution.py 的实际行为：
// - POST /prompt 请求体 { prompt, client_id }，响应 { prompt_id, number, node_errors }
// - websocket /ws?clientId=... 下发 progress / executing / executed /
//   execution_cached / execution_error / execution_interrupted / execution_success / status
// - GET /history/{prompt_id} 返回 { [prompt_id]: HistoryEntry }

export interface PromptNode {
  class_type: string
  inputs: Record<string, unknown>
}

/** ComfyUI API 格式工作流：节点 id -> 节点定义。 */
export type PromptWorkflow = Record<string, PromptNode>

export interface QueuePromptResult {
  prompt_id: string
  number: number
  node_errors: Record<string, unknown>
}

export interface OutputFile {
  filename: string
  subfolder?: string
  type?: string
}

export interface NodeOutput {
  images?: OutputFile[]
  gifs?: OutputFile[]
  [key: string]: unknown
}

export interface HistoryEntry {
  prompt: unknown
  outputs: Record<string, NodeOutput>
  status: {
    status_str: string
    completed: boolean
    messages: unknown[]
  }
}

export interface QueueState {
  queue_running: unknown[]
  queue_pending: unknown[]
}

export type WsMessage = {
  type: string
  data?: Record<string, unknown>
}

export type PromptProgress = {
  type: 'progress' | 'executing' | 'executed' | 'execution_cached'
  node?: string
  value?: number
  max?: number
}
