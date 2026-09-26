export interface ComfyDownloadProgress {
  /** Stable per-job identifier assigned by the desktop app. The download
   *  controls accept it in place of the URL. Optional: older desktop
   *  versions do not send it. */
  id?: string
  url: string
  filename: string
  directory?: string
  progress: number
  receivedBytes?: number
  totalBytes?: number
  speedBytesPerSec?: number
  etaSeconds?: number
  status: 'pending' | 'downloading' | 'paused' | 'completed' | 'error' | 'cancelled'
  error?: string
  isImage?: boolean
}
export interface TerminalRestore {
  buffer: string[]
  size: {
    cols: number
    rows: number
  }
  exited: boolean
}
export interface LogsRestore {
  installationId: string
  buffer: string[]
}
export interface LogsOutputMsg {
  installationId: string
  text: string
}
export type ComfyDesktop2TelemetryValue = string | number | boolean | null
export type ComfyDesktop2TelemetryProperties = Record<
  string,
  ComfyDesktop2TelemetryValue | ComfyDesktop2TelemetryValue[]
>
export interface ComfyDesktop2Error {
  message: string
  stack?: string
}
export type ComfyDesktop2FirebaseAuthState =
  | {
      status: 'pending'
    }
  | {
      status: 'signed_out'
    }
  | {
      status: 'signed_in'
      userId: string
    }
export interface ComfyDesktop2TerminalBridge {
  subscribe(installationId?: string): Promise<TerminalRestore>
  unsubscribe(installationId?: string): Promise<void>
  write(data: string, installationId?: string): Promise<void>
  resize(cols: number, rows: number, installationId?: string): Promise<void>
  restart(installationId?: string): Promise<TerminalRestore>
  openPopout(): Promise<void>
  onOutput(callback: (data: string) => void): () => void
  onExited(callback: () => void): () => void
}
export interface ComfyDesktop2LogsBridge {
  subscribe(installationId?: string): Promise<LogsRestore>
  unsubscribe(installationId?: string): Promise<void>
  openPopout(): Promise<void>
  onOutput(callback: (msg: LogsOutputMsg) => void): () => void
}
export interface ComfyDesktop2TelemetryBridge {
  capture(event: string, properties?: ComfyDesktop2TelemetryProperties): void
  /** Capture a hosted-frontend exception through Desktop's privacy and release-context boundary. */
  captureException?(error: ComfyDesktop2Error, properties?: ComfyDesktop2TelemetryProperties): void
  /** Report the hosted view's complete Firebase state for process-wide consensus. */
  reportFirebaseAuthState?(state: ComfyDesktop2FirebaseAuthState): void
}
/** Availability of the desktop-side comfy-studio host (MCP client + chat agent). */
export interface ComfyStudioStatus {
  installationId: string | null
  /** False when this install has no usable python/ComfyUI checkout to host from. */
  available: boolean
  running: boolean
  comfyuiDir?: string
  error?: string
}
export type ComfyStudioRequestResult =
  | {
      ok: true
      result: unknown
    }
  | {
      ok: false
      error: {
        code?: number
        message: string
      }
    }
/** A notification pushed by the host, e.g. an `agent/event` during a chat turn. */
export interface ComfyStudioEventMessage {
  installationId: string
  method: string
  params: Record<string, unknown>
}
/** Desktop-side comfy-studio host: MCP hub + skill catalog + conversation agent.
 *  `request` proxies the host's own JSON-RPC methods (see `lib/comfy_studio/server.py`). */
export interface ComfyDesktop2ComfyStudioBridge {
  status(installationId?: string): Promise<ComfyStudioStatus>
  start(installationId?: string): Promise<ComfyStudioStatus>
  stop(installationId?: string): Promise<ComfyStudioStatus>
  request(
    method: string,
    params?: Record<string, unknown>,
    installationId?: string
  ): Promise<ComfyStudioRequestResult>
  onEvent(callback: (message: ComfyStudioEventMessage) => void): () => void
}
export interface ComfyDesktop2Bridge {
  /** Reports whether the backend server is cloud/remote, not the user's location.
   *  Optional: desktop builds predating it are still in the wild. */
  isRemote?(): boolean
  openTerminal?: () => Promise<boolean>
  openMcpSetup?: () => Promise<boolean>
  /** Opens a model provider access page in the hosted frontend's browser session.
   *  Resolves `true` when the host has taken ownership of the request.
   *  On `false` or rejection the frontend falls back to opening a new tab. */
  openModelAccessPage?: (url: string) => Promise<boolean>
  downloadModel?: (url: string, filename: string, directory: string) => Promise<boolean>
  downloadAsset?: (url: string, filename: string, authToken?: string) => Promise<boolean>
  pauseDownload?: (url: string) => Promise<boolean>
  resumeDownload?: (url: string) => Promise<boolean>
  cancelDownload?: (url: string) => Promise<boolean>
  onDownloadProgress?: (callback: (data: ComfyDownloadProgress) => void) => () => void
  reportTheme?: (bg: string, text: string) => void
  Terminal?: ComfyDesktop2TerminalBridge
  Logs?: ComfyDesktop2LogsBridge
  Telemetry?: ComfyDesktop2TelemetryBridge
  ComfyStudio?: ComfyDesktop2ComfyStudioBridge
}
/**
 * The `-?` mapper intentionally requires every top-level bridge member.
 * Adding an optional top-level member to `ComfyDesktop2Bridge` is therefore a
 * breaking change for implementations of this type. Optional members of nested
 * bridge types remain optional because the mapper is not recursive.
 */
export type ComfyDesktop2BridgeImplementation = {
  [K in keyof ComfyDesktop2Bridge]-?: NonNullable<ComfyDesktop2Bridge[K]>
}
