import { describe, expect, it } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import projectsFx from '../../../test/fixtures/captured/projects.json'
import { ProjectsPage } from '..'

/* A project is renamed from its row's menu on the Projects page -- a rename is rare, so it is not
   on the project's own pages -- by its admins: PATCH /projects/{id} {name}, trimmed. The dialog
   is the page's: a click in it does not open the project. A blank or unchanged name is not sent;
   the name of another listed project is said, not refused. */

type ApiProject = (typeof projectsFx.projects)[number]

function setup({ role = 'admin' }: { role?: string } = {}) {
  let projects: ApiProject[] = projectsFx.projects.map((p) => (p.id === 'p1' ? { ...p, my_role: role } : p))
  const sent: unknown[] = []
  server.use(
    http.get(`${API_BASE_URL}/projects`, () => HttpResponse.json({ ...projectsFx, projects })),
    http.get(`${API_BASE_URL}/notifications`, () => HttpResponse.json({ notifications: [] })),
    http.patch(`${API_BASE_URL}/projects/p1`, async ({ request }) => {
      const body = await request.json() as { name: string }
      sent.push(body)
      projects = projects.map((p) => (p.id === 'p1' ? { ...p, name: body.name } : p))
      return HttpResponse.json({ project: projects.find((p) => p.id === 'p1') })
    }),
  )
  function Where() { return <output data-testid="where">{useLocation().pathname}</output> }
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/projects']}>
        <Routes>
          <Route path="/projects" element={<><ProjectsPage /><Where /></>} />
          <Route path="/projects/:projectId/overview" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { sent, user: userEvent.setup() }
}

async function openRename(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: 'Actions for VCU Engine Firmware' }))
  await user.click(await screen.findByRole('menuitem', { name: /Rename/ }))
  return screen.findByRole('dialog', { name: 'Rename project' })
}

describe('Renaming a project from the Projects page', { timeout: 30_000 }, () => {
  it("an admin's row menu has Rename first; the new name is sent trimmed and the row shows it", async () => {
    const { sent, user } = setup()
    await user.click(await screen.findByRole('button', { name: 'Actions for VCU Engine Firmware' }))
    const items = await screen.findAllByRole('menuitem')
    expect(items.map((i) => i.textContent?.replace(/^(edit|download|delete)/, ''))).toEqual(['Rename', 'Download config', 'Delete'])
    await user.click(items[0])
    const dialog = await screen.findByRole('dialog', { name: 'Rename project' })
    const box = within(dialog).getByLabelText('Project name')
    expect(box).toHaveValue('VCU Engine Firmware')
    await user.clear(box)
    await user.type(box, '  VCU Firmware 2  ')
    await user.click(within(dialog).getByRole('button', { name: /^Rename$/ }))
    await waitFor(() => expect(sent).toEqual([{ name: 'VCU Firmware 2' }]))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(await screen.findByRole('button', { name: 'Actions for VCU Firmware 2' })).toBeInTheDocument()
    expect(screen.getByTestId('where')).toHaveTextContent('/projects')       // not opened
  })

  it('a click inside the dialog does not open the project', async () => {
    const { user } = setup()
    const dialog = await openRename(user)
    await user.click(within(dialog).getByLabelText('Project name'))
    await user.click(dialog)
    expect(screen.getByTestId('where')).toHaveTextContent(/^\/projects$/)
  })

  it('a blank or unchanged name is not sent; a blank one says why', async () => {
    const { sent, user } = setup()
    const dialog = await openRename(user)
    const rename = within(dialog).getByRole('button', { name: /^Rename$/ })
    expect(rename).toBeDisabled()
    const box = within(dialog).getByLabelText('Project name')
    await user.clear(box)
    await user.type(box, '   ')
    expect(within(dialog).getByRole('alert')).toHaveTextContent('A project needs a name.')
    expect(rename).toBeDisabled()
    await user.keyboard('{Enter}')
    expect(sent).toEqual([])
  })

  it("another listed project's name is said, and still allowed", async () => {
    const { user } = setup()
    const dialog = await openRename(user)
    const box = within(dialog).getByLabelText('Project name')
    await user.clear(box)
    await user.type(box, 'adas sensor fusion')
    expect(within(dialog).getByRole('status')).toHaveTextContent('Another project is already called “adas sensor fusion”.')
    expect(within(dialog).getByRole('button', { name: /^Rename$/ })).toBeEnabled()
  })

  it("is not in a developer's menu", async () => {
    const { user } = setup({ role: 'developer' })
    await user.click(await screen.findByRole('button', { name: 'Actions for VCU Engine Firmware' }))
    expect(await screen.findByRole('menuitem', { name: /Download config/ })).toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: /Rename/ })).toBeNull()
  })
})
