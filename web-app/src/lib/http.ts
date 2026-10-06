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

/** One of FastAPI's request-validation problems (a 422's `detail` list). */
interface ValidationIssue {
  loc?: (string | number)[]
  msg?: string
}

interface ErrorEnvelope {
  error?: { code?: string; message?: string; status?: number }
  detail?: { code?: string; message?: string; status?: number } | string | ValidationIssue[]
}

/** Error thrown for any non-2xx response. Carries status + backend code. */
export class ApiError extends Error {
  status: number
  code?: string
  /** The error object's other fields, as the server sent them (snake_case): a 409's `job_id`,
   *  `components`, `writer`, … Empty when the body had none. */
  extra: Record<string, unknown>
  constructor(message: string, status: number, code?: string, extra: Record<string, unknown> = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.extra = extra
  }
}

/** The API answered 404: the thing is not there. Any other failure is a read that did not work
 *  — show it with a Retry, never as "not found". */
export function isNotFound(e: unknown): boolean {
  return e instanceof ApiError && e.status === 404
}

/** A failure worth one more try: the network (no answer) or the server (5xx). A 4xx answer —
 *  401, 403, 404, 409, 422 — is the same the second time; retrying only delayed the error page. */
export function isRetryable(e: unknown): boolean {
  return !(e instanceof ApiError) || e.status >= 500
}

/** A 422's validation problems as one readable line: the first one's field and message
 *  (`tag: Field required`), and how many more. FastAPI sends them as a `detail` list, which the
 *  envelope parsing dropped — the page said only "Unprocessable Entity". */
function validationMessage(detail: ValidationIssue[]): string | undefined {
  const first = detail.find((d) => typeof d?.msg === 'string')
  if (!first?.msg) return undefined
  // `loc` starts with where the value was sent (body, query, path): the rest names the field.
  const where = new Set(['body', 'query', 'path', 'header', 'cookie'])
  const field = (first.loc ?? []).filter((p, i) => !(i === 0 && where.has(String(p)))).join('.')
  const more = detail.length > 1 ? ` (and ${detail.length - 1} more)` : ''
  return `${field ? `${field}: ` : ''}${first.msg}${more}`
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
  let extra: Record<string, unknown> = {}
  try {
    const body = (await res.json()) as ErrorEnvelope
    const detail = body.detail
    const env = body.error ?? (detail && typeof detail === 'object' && !Array.isArray(detail) ? detail : undefined)
    if (env?.message) message = env.message
    else if (typeof detail === 'string') message = detail
    else if (Array.isArray(detail)) message = validationMessage(detail) ?? message
    code = env?.code
    if (env) {
      const rest: Record<string, unknown> = { ...env }
      delete rest.code
      delete rest.message
      delete rest.status
      extra = rest
    }
  } catch {
    /* non-JSON body — keep the status-derived message */
  }
  return new ApiError(message, res.status, code, extra)
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

/** Fetch a binary endpoint with auth (+ one-shot 401 refresh) and trigger a browser download. */
async function download(path: string, fallbackName: string, params?: QueryParams, _retry = false): Promise<void> {
  const token = useAuthStore.getState().accessToken
  const res = await fetch(buildUrl(path, params), {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  })
  // Access tokens are short-lived; without this a download after an idle spell failed where
  // any other request would have refreshed and retried.
  if (res.status === 401 && !_retry) {
    if (await refreshAccessToken()) return download(path, fallbackName, params, true)
    useAuthStore.getState().signOut()
    throw await parseError(res)
  }
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
  // Revoking in the same tick can cancel the download in some browsers.
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

export const http = {
  get: <T>(path: string, params?: QueryParams) => request<T>('GET', path, { params }),
  post: <T>(path: string, body?: unknown, params?: QueryParams) =>
    request<T>('POST', path, { body, params }),
  patch: <T>(path: string, body?: unknown, params?: QueryParams) =>
    request<T>('PATCH', path, { body, params }),
  put: <T>(path: string, body?: unknown, params?: QueryParams) =>
    request<T>('PUT', path, { body, params }),
  del: <T>(path: string, params?: QueryParams) => request<T>('DELETE', path, { params }),
  upload,
  download,
  /** Absolute URL for a backend path (binary download/export, SSE). */
  rawUrl: (path: string, params?: QueryParams) => buildUrl(path, params),
}
