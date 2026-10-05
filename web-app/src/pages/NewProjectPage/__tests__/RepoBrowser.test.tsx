import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { RepoBrowser } from '../components/RepoBrowser'

/* A Local path repository's Browse: the folders of the server ArtiFex runs on, one folder at a
   time (GET /repositories/local-folders). A plain folder opens; only a git repository is picked,
   and a double-click picks and uses it. */

type Wire = { path: string; parent: string | null; folders: { name: string; path: string; git: boolean }[]; limited?: boolean; truncated?: boolean }
const dir = (path: string, parent: string | null, folders: [string, boolean][], more: Partial<Wire> = {}): Wire => ({
  path, parent, limited: false, truncated: false, ...more,
  folders: folders.map(([name, git]) => ({ name, path: `${path.endsWith('/') ? path : `${path}/`}${name}`, git })),
})

const SERVER: Record<string, Wire> = {
  '': { path: '', parent: null, limited: false, truncated: false, folders: [
    { name: 'C:/', path: 'C:/', git: false }, { name: 'D:/', path: 'D:/', git: false }] },
  'D:/': dir('D:/', '', [['builds', false], ['src', false]]),
  'D:/src': dir('D:/src', 'D:/', [['adas-fusion', true], ['docs', false], ['vcu-firmware', true]]),
  'D:/src/docs': dir('D:/src/docs', 'D:/src', []),
}

/** The server's answers (`fs`), every `path` asked for recorded. `fail`: an answer to send instead. */
function serve(fs: Record<string, Wire> = SERVER, fail?: (path: string) => Response | undefined) {
  const asked: string[] = []
  server.use(http.get(`${API_BASE_URL}/repositories/local-folders`, ({ request }) => {
    const path = new URL(request.url).searchParams.get('path') ?? ''
    asked.push(path)
    const failed = fail?.(path)
    if (failed) return failed
    return fs[path] ? HttpResponse.json(fs[path])
      : HttpResponse.json({ detail: { code: 'NOT_FOUND', message: `No folder ${path} on the server.`, status: 404 } }, { status: 404 })
  }))
  return asked
}

function setup(start = '') {
  const onUse = vi.fn()
  const onClose = vi.fn()
  render(<RepoBrowser start={start} onUse={onUse} onClose={onClose} />)
  return { onUse, onClose, user: userEvent.setup() }
}

const crumbs = () => within(screen.getByRole('navigation', { name: 'Folder' })).getAllByRole('button').map((b) => b.textContent?.replace('dns', ''))
const row = (name: RegExp | string) => screen.getByRole('button', { name: typeof name === 'string' ? new RegExp(`^${name}`) : name })
const useBtn = () => screen.getByRole('button', { name: 'Use this repository' })

afterEach(() => { vi.restoreAllMocks() })

describe('RepoBrowser', () => {
  it('opens on the server\'s top list', async () => {
    const asked = serve()
    setup()
    expect(await screen.findByRole('button', { name: /^C:\// })).toBeInTheDocument()
    expect(row('D:/')).toBeInTheDocument()
    expect(crumbs()).toEqual(['This server'])
    expect(screen.getByText('Pick a git repository')).toBeInTheDocument()
    expect(asked).toEqual([''])
  })

  it('a folder opens, and the breadcrumb goes back', async () => {
    serve()
    const { user } = setup()
    await user.click(await screen.findByRole('button', { name: /^D:\// }))
    await user.click(await screen.findByRole('button', { name: /^src\// }))
    expect(await screen.findByRole('button', { name: /^vcu-firmware/ })).toBeInTheDocument()
    expect(crumbs()).toEqual(['This server', 'D:', 'src'])

    await user.click(within(screen.getByRole('navigation', { name: 'Folder' })).getByRole('button', { name: 'D:' }))
    expect(await screen.findByRole('button', { name: /^builds\// })).toBeInTheDocument()
    expect(crumbs()).toEqual(['This server', 'D:'])
    await user.click(within(screen.getByRole('navigation', { name: 'Folder' })).getByRole('button', { name: /This server/ }))
    expect(await screen.findByRole('button', { name: /^C:\// })).toBeInTheDocument()
  })

  it('a git repository is marked, and a click picks it without redrawing the rows', async () => {
    serve()
    const { user, onUse } = setup('D:/src/docs')
    const vcu = await screen.findByRole('button', { name: /^vcu-firmware/ })
    expect(within(vcu).getByText('git')).toBeInTheDocument()
    expect(within(row('docs/')).queryByText('git')).toBeNull()
    expect(useBtn()).toBeDisabled()

    await user.click(vcu)
    // The same row, marked in place: a double-click's second click lands on it.
    expect(row('vcu-firmware')).toBe(vcu)
    expect(vcu).toBeInTheDocument()
    expect(vcu).toHaveAttribute('aria-pressed', 'true')
    expect(row('adas-fusion')).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByText('D:/src/vcu-firmware')).toBeInTheDocument()
    expect(onUse).not.toHaveBeenCalled()

    await user.click(useBtn())
    expect(onUse).toHaveBeenCalledWith('D:/src/vcu-firmware')
  })

  it('a double-click picks and uses a repository', async () => {
    serve()
    const { user, onUse } = setup('D:/src/docs')
    await user.dblClick(await screen.findByRole('button', { name: /^adas-fusion/ }))
    expect(onUse).toHaveBeenCalledWith('D:/src/adas-fusion')
  })

  it('opens where the field points, the repository it names picked', async () => {
    const asked = serve()
    setup('"D:\\src\\vcu-firmware"')
    await waitFor(() => expect(row('vcu-firmware')).toHaveAttribute('aria-pressed', 'true'))
    expect(asked).toEqual(['D:/src'])
    expect(crumbs()).toEqual(['This server', 'D:', 'src'])
    expect(useBtn()).toBeEnabled()
  })

  it('a field the server has no folder for opens the top list', async () => {
    const asked = serve()
    setup('E:/gone/vcu')
    expect(await screen.findByRole('button', { name: /^C:\// })).toBeInTheDocument()
    expect(asked).toEqual(['E:/gone', ''])
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('an empty folder says so', async () => {
    serve()
    const { user } = setup('D:/src/vcu-firmware')
    await user.click(await screen.findByRole('button', { name: /^docs\// }))
    expect(await screen.findByText('No folders here')).toBeInTheDocument()
    expect(crumbs()).toEqual(['This server', 'D:', 'src', 'docs'])
  })

  it('a read that fails says why, and Retry reads again', async () => {
    let failing = true
    serve(SERVER, () => (failing
      ? HttpResponse.json({ detail: { code: 'INTERNAL', message: 'The disk could not be read.', status: 500 } }, { status: 500 })
      : undefined))
    const { user } = setup()
    expect(await screen.findByRole('alert')).toHaveTextContent('The disk could not be read.')
    failing = false
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('button', { name: /^D:\// })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('a folder the server refuses says so', async () => {
    serve(SERVER, (p) => (p === 'C:/'
      ? HttpResponse.json({ detail: { code: 'FORBIDDEN', message: 'C:/ is outside the folders this server allows.', status: 403 } }, { status: 403 })
      : undefined))
    const { user } = setup()
    await user.click(await screen.findByRole('button', { name: /^C:\// }))
    expect(await screen.findByRole('alert')).toHaveTextContent('C:/ is outside the folders this server allows.')
  })

  it('a long folder says only the first folders are shown', async () => {
    serve({ ...SERVER, 'D:/': { ...SERVER['D:/'], truncated: true } })
    setup('D:/src')
    expect(await screen.findByText('Showing the first 2 folders')).toBeInTheDocument()
  })

  it('in a server that limits the picker, the breadcrumb starts at the allowed folder', async () => {
    const limited: Record<string, Wire> = {
      '': { path: '', parent: null, limited: true, truncated: false, folders: [{ name: 'D:/src', path: 'D:/src', git: false }] },
      'D:/src': dir('D:/src', '', [['third_party', false]], { limited: true }),
      'D:/src/third_party': dir('D:/src/third_party', 'D:/src', [['lwip', true]], { limited: true }),
    }
    serve(limited)
    setup('D:/src/third_party/lwip')
    await waitFor(() => expect(row('lwip')).toHaveAttribute('aria-pressed', 'true'))
    await waitFor(() => expect(crumbs()).toEqual(['This server', 'D:/src', 'third_party']))
  })

  it('Esc, Cancel and the close button close it', async () => {
    serve()
    const { user, onClose } = setup()
    await screen.findByRole('button', { name: /^C:\// })
    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledTimes(1)
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await user.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledTimes(3)
  })
})
