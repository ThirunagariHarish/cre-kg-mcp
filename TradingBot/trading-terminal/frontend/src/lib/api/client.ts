/**
 * Typed fetch wrapper for the SelfAgentBot API.
 *
 * All requests attach an Authorization: Bearer header using the token
 * from VITE_API_TOKEN. On 401 the error is logged to console. On any
 * network failure a descriptive Error is thrown. JSON parse failures are
 * caught and re-thrown with context.
 */

export const API_BASE: string =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8765'

let _authToken: string = import.meta.env.VITE_API_TOKEN ?? ''

export function setAuthToken(token: string): void {
  _authToken = token
}

function buildHeaders(extra?: HeadersInit): HeadersInit {
  return {
    'Content-Type': 'application/json',
    ...(_authToken ? { Authorization: `Bearer ${_authToken}` } : {}),
    ...(extra ?? {}),
  }
}

export interface FetchOptions extends Omit<RequestInit, 'headers'> {
  /** Optional AbortController signal for cancellation. */
  signal?: AbortSignal
  headers?: HeadersInit
}

/**
 * Base fetch function. All other helpers delegate here.
 */
export async function apiFetch<T>(
  path: string,
  init: FetchOptions = {}
): Promise<T> {
  const { headers: extraHeaders, ...rest } = init
  const url = `${API_BASE}${path}`

  let response: Response
  try {
    response = await fetch(url, {
      ...rest,
      headers: buildHeaders(extraHeaders),
    })
  } catch (err: unknown) {
    const message =
      err instanceof Error ? err.message : 'Network request failed'
    throw new Error(`[API] Network error for ${path}: ${message}`)
  }

  if (response.status === 401) {
    console.error(`[API] 401 Unauthorized — check VITE_API_TOKEN for ${path}`)
    throw new Error(`[API] 401 Unauthorized: ${path}`)
  }

  if (!response.ok) {
    throw new Error(`[API] ${response.status} ${response.statusText}: ${path}`)
  }

  // Handle empty body (e.g. 204 No Content)
  const contentLength = response.headers.get('content-length')
  if (response.status === 204 || contentLength === '0') {
    return undefined as unknown as T
  }

  try {
    return (await response.json()) as T
  } catch (err: unknown) {
    const message =
      err instanceof Error ? err.message : 'JSON parse failed'
    throw new Error(`[API] Failed to parse response from ${path}: ${message}`)
  }
}

/**
 * Typed GET request. Appends optional URLSearchParams query string.
 */
export async function apiGet<T>(
  path: string,
  params?: Record<string, string | number | boolean | undefined>,
  signal?: AbortSignal
): Promise<T> {
  let fullPath = path
  if (params) {
    const qs = new URLSearchParams()
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined) qs.set(k, String(v))
    }
    const str = qs.toString()
    if (str) fullPath = `${path}?${str}`
  }
  return apiFetch<T>(fullPath, { method: 'GET', signal })
}

/**
 * Typed POST request with optional JSON body.
 */
export async function apiPost<T>(
  path: string,
  body?: unknown,
  signal?: AbortSignal
): Promise<T> {
  return apiFetch<T>(path, {
    method: 'POST',
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  })
}

/**
 * Typed DELETE request.
 */
export async function apiDelete<T>(
  path: string,
  signal?: AbortSignal
): Promise<T> {
  return apiFetch<T>(path, { method: 'DELETE', signal })
}
