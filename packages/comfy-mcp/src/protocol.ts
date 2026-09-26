import { createInterface } from 'node:readline'

export type RpcHandler = (params: unknown) => unknown | Promise<unknown>

/**
 * MCP stdio 传输的极简实现：行分隔的 JSON-RPC 2.0（tools 能力子集）。
 * 规范见 modelcontextprotocol.io；不引 SDK，避免版本绑定。
 */
export class StdioRpcServer {
  private handlers = new Map<string, RpcHandler>()

  constructor(private readonly serverInfo: { name: string; version: string }) {}

  on(method: string, handler: RpcHandler): this {
    this.handlers.set(method, handler)
    return this
  }

  start(): void {
    const rl = createInterface({ input: process.stdin })
    rl.on('line', line => {
      const text = line.trim()
      if (text === '') return
      let msg: { jsonrpc?: string; id?: unknown; method?: string; params?: unknown }
      try {
        msg = JSON.parse(text)
      } catch {
        this.sendError(null, -32700, `请求不是合法 JSON: ${text.slice(0, 200)}`)
        return
      }
      if (msg.id === undefined || msg.id === null) return // notification，不需要响应
      const handler = msg.method !== undefined ? this.handlers.get(msg.method) : undefined
      if (handler === undefined) {
        this.sendError(msg.id, -32601, `未知方法: ${String(msg.method)}`)
        return
      }
      Promise.resolve()
        .then(() => handler(msg.params))
        .then(
          result => this.sendMessage({ jsonrpc: '2.0', id: msg.id, result }),
          err => this.sendError(msg.id, -32603, err instanceof Error ? err.message : String(err)),
        )
    })
    rl.on('close', () => process.exit(0))
  }

  get info(): { name: string; version: string } {
    return this.serverInfo
  }

  private sendMessage(obj: unknown): void {
    process.stdout.write(`${JSON.stringify(obj)}\n`)
  }

  private sendError(id: unknown, code: number, message: string): void {
    this.sendMessage({ jsonrpc: '2.0', id, error: { code, message } })
  }
}
