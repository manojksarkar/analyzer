import { describe, expect, it } from 'vitest'
import { http as mock, HttpResponse } from 'msw'
import { server } from '../../test/server'
import { API_BASE_URL, ApiError, http, isRetryable } from '../http'
import { queryClient, retryQuery } from '../queryClient'

/* UI review #18, #19: a 422 said only "Unprocessable Entity" (FastAPI's `detail` list was dropped),
   and every failed read was retried — a 401/403/404 too, which only delayed the error page. */

async function failure(body: unknown, status: number): Promise<ApiError> {
  server.use(mock.post(`${API_BASE_URL}/things`, () => HttpResponse.json(body, { status })))
  try {
    await http.post('/things', {})
  } catch (e) {
    return e as ApiError
  }
  throw new Error('the request did not fail')
}

describe('http errors', () => {
  it("a 422 says the first field and its message, and how many more", async () => {
    const e = await failure({
      detail: [
        { type: 'missing', loc: ['body', 'tag'], msg: 'Field required' },
        { type: 'string_too_long', loc: ['body', 'description'], msg: 'String should have at most 200 characters' },
      ],
    }, 422)
    expect(e).toBeInstanceOf(ApiError)
    expect(e.status).toBe(422)
    expect(e.message).toBe('tag: Field required (and 1 more)')
  })

  it('a nested field is named by its path', async () => {
    const e = await failure({ detail: [{ loc: ['body', 'scope', 'names', 0], msg: 'Input should be a valid string' }] }, 422)
    expect(e.message).toBe('scope.names.0: Input should be a valid string')
  })

  it('a 422 with nothing readable keeps the status text', async () => {
    const e = await failure({ detail: [] }, 422)
    expect(e.status).toBe(422)
    expect(e.message).not.toBe('')
  })

  it("the API's own envelope still wins", async () => {
    const e = await failure({ detail: { code: 'WRONG_STATE', message: 'Not in review', status: 409 } }, 409)
    expect(e.message).toBe('Not in review')
    expect(e.code).toBe('WRONG_STATE')
  })
})

describe('retry', () => {
  it('retries a network failure or a 5xx once, never a 4xx', () => {
    expect(isRetryable(new TypeError('Failed to fetch'))).toBe(true)
    expect(isRetryable(new ApiError('down', 503))).toBe(true)
    for (const status of [400, 401, 403, 404, 409, 422]) {
      expect(isRetryable(new ApiError('no', status))).toBe(false)
    }
    expect(retryQuery(0, new ApiError('down', 500))).toBe(true)
    expect(retryQuery(1, new ApiError('down', 500))).toBe(false)
    expect(retryQuery(0, new ApiError('gone', 404))).toBe(false)
  })

  it("is the app's default for every read", () => {
    expect(queryClient.getDefaultOptions().queries?.retry).toBe(retryQuery)
  })
})
