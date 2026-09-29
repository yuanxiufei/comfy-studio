/**
 * One typed door to the host RPC for the section pages.
 *
 * The bridge's envelope is `{ok:true,result} | {ok:false,error}`, and a dead IPC
 * channel rejects instead of answering. Both are failures the page must render,
 * so both are normalised here into one shape — otherwise every store would
 * re-implement the same two-branch handling, and one of them would forget the
 * `catch` and leave a spinner running forever.
 *
 * `value` is `null` whenever `ok` is false: the caller checks `ok` and then the
 * cast to `T` is honest, because `T` describes the host's success payload.
 */
import { useStudioStore } from '../../stores/studioStore'

export interface RpcOutcome<T> {
  ok: boolean
  value: T | null
  /** Host message, or the transport's own — always renderable prose. */
  error: string
}

export async function callStudio<T>(
  method: string,
  params: Record<string, unknown> = {}
): Promise<RpcOutcome<T>> {
  const studio = useStudioStore()
  try {
    const response = await studio.request(method, params)
    if (!response.ok) {
      return { ok: false, value: null, error: response.error.message }
    }
    return { ok: true, value: response.result as T, error: '' }
  } catch (caught) {
    // The channel itself went away (host process died mid-call).
    return { ok: false, value: null, error: caught instanceof Error ? caught.message : String(caught) }
  }
}
