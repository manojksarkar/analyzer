import { useAuthStore } from '../store/auth'

/**
 * Single HTTP client for the FastAPI backend (base path `/api/v1`).
 *
 * Responsibilities:
 *  - Prefix every request with `VITE_API_URL` (defaults to local dev server).
 *  - Inject `Authorization: Bearer <accessToken>` from the auth store.
 *  - Unwrap the `{ error: { message } }` envelope into a thrown `Error` whose
 *    `.message` is user-facing (the pages already surface `err.message`).
 *  - On 401, transparently refresh the access token once and retry; if refresh
 *    fails, sign the user out (ProtectedRoute then redirects to /signin).
 *
 * The store is read via `getState()` inside function bodies (never at module
 * load) so the store ↔ services ↔ http import cycle resolves cleanly.
 */

export const API_BASE_URL: string =
  (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000/api/v1'

type QueryValue = string | number | boolean | null | undefined
export type QueryParams = Record<string, QueryValue | QueryValue[]>

interface RequestOptions {
  /** JSON request body (objects are serialised; omit for GET/DELETE). */
  body?: unknown
  /** Query-string params; arrays repeat the key, nullish values are skipped. */
  params?: QueryParams
  /** Internal: prevents infinite refresh loops. */
  _retry?: boolean
  /** Skip the Bearer header (used by the refresh call itself). */
  skipAuth?: boolean
}

interface ErrorEnvelope {
  error?: { code?: string; message?: string; status?: number }
  detail?: { code?: string; message?: string; status?: number } | string
}

/** Error thrown for any non-2xx response. Carries status + backend code. */
export class ApiError extends Error {
  status: number
  code?: string
  constructor(message: string, status: number, code?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

function buildUrl(path: string, params?: QueryParams): string {
  const url = new URL(API_BASE_URL + path)
  if (params) {
    for (const [key, raw] of Object.entries(params)) {
      const values = Array.isArray(raw) ? raw : [raw]
      for (const v of values) {
        if (v !== null && v !== undefined && v !== '') url.searchParams.append(key, String(v))
      }
    }
  }
  return url.toString()
}

async function parseError(res: Response): Promise<ApiError> {
  let message = res.statusText || `Request failed (${res.status})`
  let code: string | undefined
  try {
    const body = (await res.json()) as ErrorEnvelope
    const env = body.error ?? (typeof body.detail === 'object' ? body.detail : undefined)
    if (env?.message) message = env.message
    else if (typeof body.detail === 'string') message = body.detail
    code = env?.code
  } catch {
    /* non-JSON body — keep the status-derived message */
  }
  return new ApiError(message, res.status, code)
}

/** Exchange the stored refresh token for a fresh access token. */
async function refreshAccessToken(): Promise<boolean> {
  const { refreshToken, setAccessToken } = useAuthStore.getState()
  if (!refreshToken) return false
  try {
    const res = await fetch(buildUrl('/auth/refresh'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
    if (!res.ok) return false
    const data = (await res.json()) as { access_token?: string }
    if (!data.access_token) return false
    setAccessToken(data.access_token)
    return true
  } catch {
    return false
  }
}

async function request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
  const { body, params, _retry, skipAuth } = opts
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (!skipAuth) {
    const token = useAuthStore.getState().accessToken
    if (token) headers['Authorization'] = `Bearer ${token}`
  }

  const res = await fetch(buildUrl(path, params), {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (res.status === 401 && !skipAuth && !_retry) {
    const refreshed = await refreshAccessToken()
    if (refreshed) return request<T>(method, path, { ...opts, _retry: true })
    useAuthStore.getState().signOut()
    throw await parseError(res)
  }

  if (!res.ok) throw await parseError(res)

  if (res.status === 204) return undefined as T
  // Some endpoints (download/export) return binary; callers that need bytes use
  // `rawUrl` + their own fetch. JSON endpoints are the default here.
  const text = await res.text()
  return (text ? JSON.parse(text) : undefined) as T
}

/**
 * Multipart upload with auth + one-shot 401 refresh. The browser sets the
 * `multipart/form-data` boundary itself, so we must NOT set Content-Type.
 */
async function upload<T>(path: string, form: FormData, _retry = false): Promise<T> {
  const token = useAuthStore.getState().accessToken
  const res = await fetch(buildUrl(path), {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body: form,
  })
  if (res.status === 401 && !_retry) {
    if (await refreshAccessToken()) return upload<T>(path, form, true)
    useAuthStore.getState().signOut()
    throw await parseError(res)
  }
  if (!res.ok) throw await parseError(res)
  const text = await res.text()
  return (text ? JSON.parse(text) : undefined) as T
}

/** Fetch a binary endpoint with auth and trigger a browser download. */
async function download(path: string, fallbackName: string, params?: QueryParams): Promise<void> {
  const token = useAuthStore.getState().accessToken
  const res = await fetch(buildUrl(path, params), {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  })
  if (!res.ok) throw await parseError(res)
  const blob = await res.blob()
  const disposition = res.headers.get('Content-Disposition') ?? ''
  const match = /filename="?([^"]+)"?/.exec(disposition)
  const name = match?.[1] ?? fallbackName
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export const http = {
  get: <T>(path: string, params?: QueryParams) => request<T>('GET', path, { params }),
  post: <T>(path: string, body?: unknown, params?: QueryParams) =>
    request<T>('POST', path, { body, params }),
  patch: <T>(path: string, body?: unknown, params?: QueryParams) =>
    request<T>('PATCH', path, { body, params }),
  del: <T>(path: string, params?: QueryParams) => request<T>('DELETE', path, { params }),
  upload,
  download,
  /** Absolute URL for a backend path (binary download/export, SSE). */
  rawUrl: (path: string, params?: QueryParams) => buildUrl(path, params),
}
