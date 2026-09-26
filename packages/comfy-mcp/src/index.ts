import { resolve } from 'node:path'
import { ComfyClient } from 'comfy-sdk'
import { loadSkills } from 'comfy-skills'
import { StdioRpcServer } from './protocol'
import { buildTools, errorResult } from './tools'

async function main(): Promise<void> {
  const baseUrl = process.env.COMFY_URL ?? 'http://127.0.0.1:8188'
  const skillsDir =
    process.env.COMFY_SKILLS_DIR ?? resolve(process.cwd(), 'packages/comfy-skills/skills')
  const client = new ComfyClient(baseUrl)
  const skills = loadSkills(skillsDir)
  const tools = buildTools(client, skills)

  const server = new StdioRpcServer({ name: 'comfy-studio-mcp', version: '0.1.0' })

  server.on('initialize', () => ({
    protocolVersion: '2024-11-05',
    capabilities: { tools: {} },
    serverInfo: server.info,
  }))

  server.on('tools/list', () => ({
    tools: tools.map(({ name, description, inputSchema }) => ({ name, description, inputSchema })),
  }))

  server.on('tools/call', (params: any) => {
    const tool = tools.find(t => t.name === params?.name)
    if (tool === undefined) {
      return errorResult(new Error(`未知工具: ${String(params?.name)}；可用: ${tools.map(t => t.name).join(', ')}`))
    }
    return tool.handler(params.arguments).catch(errorResult)
  })

  process.stderr.write(
    `comfy-studio mcp server 就绪: server=${baseUrl}, skills=${skills.length}, tools=${tools.length}\n`,
  )
  server.start()
}

main().catch(err => {
  process.stderr.write(`${err instanceof Error ? (err.stack ?? err.message) : String(err)}\n`)
  process.exit(1)
})
