import { randomUUID } from 'node:crypto'
import WebSocket from 'ws'
import type {
  HistoryEntry,
  PromptProgress,
  PromptWorkflow,
  QueuePromptResult,
  QueueState,
  WsMessage,
} from './types'

export class ComfyClientError extends Error {}

function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}

export class ComfyClient {
  readonly baseUrl: string
  readonly clientId: string

  constructor(baseUrl: string = process.env.COMFY_URL ?? 'http://127.0.0.1:8188') {
    this.baseUrl = baseUrl.replace(/\/+$/, '')
    this.clientId = randomUUID()
  }

  /** 输出文件的下载 URL（GET /view）。 */
  viewUrl(filename: string, subfolder = '', type = 'output'): string {
    const q = new URLSearchParams({ filename, subfolder, type })
    return `${this.baseUrl}/view?${q.toString()}`
  }

  /** 轮询直到服务可用；首次启动时模型目录扫描可能要几十秒。 */
  async waitUntilHealthy(timeoutMs = 180_000, intervalMs = 1000): Promise<void> {
    const deadline = Date.now() + timeoutMs
    for (;;) {
      try {
        const res = await fetch(`${this.baseUrl}/`)
        if (res.ok) return
      } catch {
        // 服务尚未监听，继续等
      }
      if (Date.now() > deadline) {
        throw new ComfyClientError(`等待 ComfyUI 就绪超时（${timeoutMs}ms）：${this.baseUrl}`)
      }
      await delay(intervalMs)
    }
  }

  private async request(path: string, init?: RequestInit): Promise<any> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
    if (!res.ok) {
      const body = await res.text().catch(() => '')
      throw new ComfyClientError(`ComfyUI ${path} 返回 ${res.status}: ${body.slice(0, 2000)}`)
    }
    return res.json()
  }

  async objectInfo(): Promise<Record<string, any>> {
    return this.request('/object_info')
  }

  async objectInfoNode(nodeClass: string): Promise<Record<string, any>> {
    return this.request(`/object_info/${encodeURIComponent(nodeClass)}`)
  }

  async queuePrompt(prompt: PromptWorkflow): Promise<QueuePromptResult> {
    return this.request('/prompt', {
      method: 'POST',
      body: JSON.stringify({ prompt, client_id: this.clientId }),
    })
  }

  async history(promptId: string): Promise<Record<string, HistoryEntry>> {
    return this.request(`/history/${encodeURIComponent(promptId)}`)
  }

  async queue(): Promise<QueueState> {
    return this.request('/queue')
  }

  async interrupt(): Promise<void> {
    const res = await fetch(`${this.baseUrl}/interrupt`, { method: 'POST' })
    if (!res.ok) {
      throw new ComfyClientError(`interrupt 返回 ${res.status}`)
    }
  }

  /**
   * 订阅 websocket 等待一次 prompt 执行结束，返回对应 history 记录。
   * 结果以 GET /history 为准（executed 消息与 execution_success 的到达顺序不可依赖）。
   */
  async waitForPrompt(
    promptId: string,
    onProgress?: (p: PromptProgress) => void,
    timeoutMs = 3_600_000,
  ): Promise<HistoryEntry> {
    return new Promise((resolve, reject) => {
      let settled = false
      let timer: NodeJS.Timeout | undefined
      const url = this.wsUrl()
      const ws = new WebSocket(url)

      const finish = (err?: Error, value?: HistoryEntry) => {
        if (settled) return
        settled = true
        if (timer !== undefined) clearTimeout(timer)
        try {
          ws.close()
        } catch {
          // 已关闭
        }
        if (err !== undefined) reject(err)
        else if (value !== undefined) resolve(value)
      }

      const setTimer = () => {
        timer = setTimeout(
          () => finish(new ComfyClientError(`等待 prompt ${promptId} 超时（${timeoutMs}ms）`)),
          timeoutMs,
        )
      }

      ws.on('message', (data, isBinary) => {
        if (isBinary) return // 中间预览是二进制帧
        let msg: WsMessage
        try {
          msg = JSON.parse(data.toString())
        } catch {
          return
        }
        const d = msg.data as { prompt_id?: string } | undefined
        if (d !== undefined && d.prompt_id !== undefined && d.prompt_id !== promptId) return
        switch (msg.type) {
          case 'execution_error': {
            const e = msg.data as {
              node: string
              node_type?: string
              exception_type?: string
              exception_message?: string
            }
            finish(
              new ComfyClientError(
                `节点 ${e.node} (${e.node_type ?? '?'}) 执行失败: ${e.exception_type ?? ''}: ${e.exception_message ?? ''}`,
              ),
            )
            break
          }
          case 'execution_interrupted':
            finish(new ComfyClientError(`prompt ${promptId} 被中断`))
            break
          case 'execution_success':
            this.history(promptId).then(
              h => {
                const entry = h[promptId]
                if (entry === undefined) {
                  finish(new ComfyClientError(`prompt ${promptId} 已完成但 history 中没有记录`))
                } else {
                  finish(undefined, entry)
                }
              },
              err => finish(err instanceof Error ? err : new ComfyClientError(String(err))),
            )
            break
          case 'progress':
            onProgress?.({
              type: 'progress',
              node: (msg.data as { node?: string }).node,
              value: (msg.data as { value?: number }).value,
              max: (msg.data as { max?: number }).max,
            })
            break
          case 'executing':
          case 'executed':
          case 'execution_cached':
            onProgress?.({
              type: msg.type,
              node: (msg.data as { node?: string }).node,
            })
            break
          default:
            break
        }
      })
      ws.on('error', err => finish(new ComfyClientError(`websocket 连接 ${url} 失败: ${err.message}`)))
      ws.on('close', () => {
        if (!settled) {
          finish(new ComfyClientError(`websocket 在 prompt ${promptId} 完成前被关闭（ComfyUI 进程是否退出了？）`))
        }
      })
      setTimer()
    })
  }

  private wsUrl(): string {
    const url = new URL(this.baseUrl)
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${url.toString().replace(/\/+$/, '')}/ws?clientId=${encodeURIComponent(this.clientId)}`
  }
}
