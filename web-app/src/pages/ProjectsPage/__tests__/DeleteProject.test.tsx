import { describe, expect, it } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import projectsFx from '../../../test/fixtures/captured/projects.json'
import { useToastStore } from '../../../components/ui/Toast'
import { ProjectsPage } from '..'

/* NW-4 (docs/ui-mockups/projects.html): a project is deleted from its row's menu by its admins.
   Everything of it goes, so Delete turns on only once its name is typed; a click in the dialog
   does not open the project; a refusal (a run is going) is said, and the project stays. */

type ApiProject = (typeof projectsFx.projects)[number]

function setup({ refuse = false } = {}) {
  let projects: ApiProject[] = projectsFx.projects.map((p) => (p.id === 'p1' ? { ...p, my_role: 'admin' } : p))
  const deleted: string[] = []
  server.use(
    http.get(`${API_BASE_URL}/projects`, () => HttpResponse.json({ ...projectsFx, projects })),
    http.get(`${API_BASE_URL}/notifications`, () => HttpResponse.json({ notifications: [] })),
    http.delete(`${API_BASE_URL}/projects/p1`, () => {
      if (refuse) {
        return HttpResponse.json({ detail: { code: 'JOB_RUNNING', status: 409,
          message: 'A run is writing a version of this project. Let it end, or stop it, before deleting the project.' } },
        { status: 409 })
      }
      deleted.push('p1')
      projects = projects.filter((p) => p.id !== 'p1')
      return new HttpResponse(null, { status: 204 })
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
  return { deleted, user: userEvent.setup() }
}

async function openDelete(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: 'Actions for VCU Engine Firmware' }))
  await user.click(await screen.findByRole('menuitem', { name: /Delete/ }))
  return screen.findByRole('dialog', { name: 'Delete project' })
}

describe('Deleting a project from the Projects page', { timeout: 30_000 }, () => {
  it('turns Delete on only for the exact name, then deletes it', async () => {
    const { deleted, user } = setup()
    const dialog = await openDelete(user)
    expect(dialog).toHaveTextContent('Delete VCU Engine Firmware?')
    const box = within(dialog).getByLabelText('Type the project name to delete it')
    const del = within(dialog).getByRole('button', { name: /^Delete$/ })
    expect(del).toBeDisabled()
    await user.type(box, 'VCU Engine')
    expect(del).toBeDisabled()
    await user.type(box, ' Firmware  ')
    expect(del).toBeEnabled()
    await user.click(del)
    await waitFor(() => expect(deleted).toEqual(['p1']))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Delete project' })).toBeNull())
    expect(screen.getByTestId('where')).toHaveTextContent('/projects')
  })

  it('says why when a run is going, and keeps the project', async () => {
    useToastStore.setState({ toasts: [] })
    const { deleted, user } = setup({ refuse: true })
    const dialog = await openDelete(user)
    await user.type(within(dialog).getByLabelText('Type the project name to delete it'), 'VCU Engine Firmware')
    await user.click(within(dialog).getByRole('button', { name: /^Delete$/ }))
    await waitFor(() => expect(useToastStore.getState().toasts.map((t) => `${t.title}: ${t.description}`))
      .toContain('Not deleted: A run is writing a version of this project. Let it end, or stop it, before deleting the project.'))
    expect(deleted).toEqual([])
    expect(screen.getByText('VCU Engine Firmware')).toBeInTheDocument()
  })
})
