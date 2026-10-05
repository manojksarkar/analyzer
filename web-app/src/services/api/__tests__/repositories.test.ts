import { describe, expect, it } from 'vitest'
import { http as mock, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { repositoriesApi } from '../repositories'

/* A private repository's access token went in the query string of GET /repositories/browse, so
   the server's access log, proxies and the browser's dev tools all recorded it. The tree is now
   asked for with a POST whose body carries the token; the URL carries nothing. */

const TREE = [{ type: 'file', name: 'a.cpp', path: 'a.cpp' }]

function captureBrowse() {
  const seen: { method: string; url: string; body: unknown }[] = []
  server.use(
    mock.all(`${API_BASE_URL}/repositories/browse`, async ({ request }) => {
      const text = await request.text()
      seen.push({ method: request.method, url: request.url, body: text ? JSON.parse(text) : null })
      return HttpResponse.json({ entries: TREE })
    }),
  )
  return seen
}

describe('repositoriesApi.browse', () => {
  it('sends the token in the body of a POST, not in the URL', async () => {
    const seen = captureBrowse()
    const entries = await repositoriesApi.browse('https://git.example/r.git', 'main', '', 'ghp_secret', true)

    expect(entries).toEqual(TREE)
    expect(seen).toHaveLength(1)
    const [req] = seen
    expect(req.method).toBe('POST')
    expect(new URL(req.url).search).toBe('')
    expect(req.url).not.toContain('ghp_secret')
    expect(req.body).toEqual({
      repo_url: 'https://git.example/r.git',
      ref: 'main',
      path: '',
      access_token: 'ghp_secret',
      refresh: true,
    })
  })

  it('a public repository: no token, and no empty ref, in the body', async () => {
    const seen = captureBrowse()
    await repositoriesApi.browse('https://git.example/r.git', '', '', '')

    expect(seen[0].method).toBe('POST')
    expect(seen[0].body).toEqual({ repo_url: 'https://git.example/r.git', path: '', refresh: false })
  })
})

/* A Local path repository's Browse: GET /repositories/local-folders?path=, one folder at a time. */
describe('repositoriesApi.localFolders', () => {
  it('asks for a folder by its full path; the top list with no path', async () => {
    const urls: string[] = []
    server.use(mock.get(`${API_BASE_URL}/repositories/local-folders`, ({ request }) => {
      urls.push(request.url)
      const path = new URL(request.url).searchParams.get('path') ?? ''
      return HttpResponse.json(path
        ? { path, parent: 'D:/', folders: [{ name: 'vcu', path: `${path}/vcu`, git: true }], limited: false, truncated: true }
        : { path: '', parent: null, folders: [{ name: 'D:/', path: 'D:/', git: false }] })
    }))

    expect(await repositoriesApi.localFolders('D:/src')).toEqual({
      path: 'D:/src', parent: 'D:/', folders: [{ name: 'vcu', path: 'D:/src/vcu', git: true }], limited: false, truncated: true,
    })
    expect(await repositoriesApi.localFolders()).toEqual({
      path: '', parent: null, folders: [{ name: 'D:/', path: 'D:/', git: false }], limited: false, truncated: false,
    })
    expect(new URL(urls[0]).searchParams.get('path')).toBe('D:/src')
    expect(new URL(urls[1]).search).toBe('')
  })
})
