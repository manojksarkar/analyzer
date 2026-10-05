import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '../../test/server'
import { API_BASE_URL } from '../../lib/http'
import { queryClient } from '../../lib/queryClient'
import { useAuthStore } from '../auth'
import { loadDraft, saveDraft } from '../../pages/NewProjectPage/draft'

/* Sign-out ends everything the tab knew; only the API saying no to a token ends a session. */

const USER = { id: 'u1', name: 'Alice', email: 'alice@aspice.dev', initials: 'AL' }

function signedIn() {
  useAuthStore.setState({
    user: USER, accessToken: 'access', refreshToken: 'refresh', isAuthenticated: true, bootstrapped: false,
  })
}

/** /auth/me answers `status`; a refresh is refused (as for an expired session). */
function meAnswers(status: number | 'network') {
  server.use(
    http.get(`${API_BASE_URL}/auth/me`, () =>
      status === 'network' ? HttpResponse.error() : HttpResponse.json({ error: { message: 'no' } }, { status })),
    http.post(`${API_BASE_URL}/auth/refresh`, () => HttpResponse.json({}, { status: 401 })),
  )
}

describe('auth store', () => {
  beforeEach(signedIn)
  afterEach(() => {
    useAuthStore.setState({ user: null, accessToken: null, refreshToken: null, isAuthenticated: false })
    queryClient.clear()
  })

  it("sign-out drops every cached read, so the next user never sees this one's data", () => {
    queryClient.setQueryData(['projects', 'list', USER.email], [{ id: 'p1' }])
    queryClient.setQueryData(['projects', 'p1', 'documents', {}], [{ id: 'd1' }])
    useAuthStore.getState().signOut()
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0)
    expect(useAuthStore.getState()).toMatchObject({ user: null, accessToken: null, isAuthenticated: false })
  })

  it("sign-out drops the New Project wizard's draft, so the next user does not get it", () => {
    saveDraft({
      step: 2, done: [0, 1], name: 'Secret FW', repoUrl: 'https://git.example/fw.git', branch: 'main', tokenUsed: true,
      cores: [], layers: [], fileAssignments: {}, members: [], imported: null, importKept: [], archEdited: false,
    })
    expect(loadDraft()?.name).toBe('Secret FW')
    useAuthStore.getState().signOut()
    expect(loadDraft()).toBeNull()
  })

  it.each([500, 503, 'network' as const])('a %s from /auth/me keeps the session', async (status) => {
    meAnswers(status)
    await useAuthStore.getState().bootstrap()
    expect(useAuthStore.getState()).toMatchObject({
      user: USER, accessToken: 'access', refreshToken: 'refresh', isAuthenticated: true, bootstrapped: true,
    })
  })

  it.each([401, 403])('a %s from /auth/me signs out', async (status) => {
    queryClient.setQueryData(['projects', 'list', USER.email], [{ id: 'p1' }])
    meAnswers(status)
    await useAuthStore.getState().bootstrap()
    expect(useAuthStore.getState()).toMatchObject({
      user: null, accessToken: null, refreshToken: null, isAuthenticated: false, bootstrapped: true,
    })
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0)
  })

  it('a good /auth/me refreshes the user', async () => {
    server.use(http.get(`${API_BASE_URL}/auth/me`, () =>
      HttpResponse.json({ user: { id: 'u1', name: 'Alice M', email: 'alice@aspice.dev', initials: 'AM' } })))
    await useAuthStore.getState().bootstrap()
    expect(useAuthStore.getState()).toMatchObject({ isAuthenticated: true, bootstrapped: true })
    expect(useAuthStore.getState().user?.name).toBe('Alice M')
  })
})
