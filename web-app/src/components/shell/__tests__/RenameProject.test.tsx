import { describe, expect, it } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import project from '../../../test/fixtures/captured/project.json'
import projects from '../../../test/fixtures/captured/projects.json'
import versions from '../../../test/fixtures/captured/versions.json'
import commits from '../../../test/fixtures/captured/commits.json'
import { Subbar } from '../Subbar'

/* A project's admins rename it from the Subbar's project menu (on every page of the project):
   PATCH /projects/{id} {name}. The name is trimmed; a blank one, or the same one, is not sent;
   a refusal keeps the dialog open. Someone who is not an admin is not offered it. */

function setup({ canRename = true, refuse = false } = {}) {
  const sent: unknown[] = []
  server.use(
    http.get(`${API_BASE_URL}/projects`, () => HttpResponse.json(projects)),
    http.get(`${API_BASE_URL}/projects/p1`, () => HttpResponse.json(project)),
    http.get(`${API_BASE_URL}/projects/p1/versions`, () => HttpResponse.json(versions)),
    http.get(`${API_BASE_URL}/projects/p1/commits`, () => HttpResponse.json(commits)),
    http.get(`${API_BASE_URL}/projects/p1/jobs/current`, () => HttpResponse.json({ job: null })),
    http.patch(`${API_BASE_URL}/projects/p1`, async ({ request }) => {
      const body = await request.json() as { name?: string }
      sent.push(body)
      if (refuse) {
        return HttpResponse.json({ detail: { code: 'VALIDATION_ERROR', message: 'A project needs a name.', status: 400 } }, { status: 400 })
      }
      return HttpResponse.json({ project: { ...project.project, name: body.name } })
    }),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/projects/p1/overview']}>
        <Routes>
          <Route path="/projects/:projectId/overview" element={<Subbar projectName="VCU Engine Firmware" canRename={canRename} />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { sent, user: userEvent.setup() }
}

const openMenu = async (user: ReturnType<typeof userEvent.setup>) =>
  user.click(screen.getByRole('button', { name: /VCU Engine Firmware/ }))

describe('Renaming a project', { timeout: 30_000 }, () => {
  it('an admin renames it from the project menu; the name is sent trimmed', async () => {
    const { sent, user } = setup()
    await openMenu(user)
    await user.click(await screen.findByRole('button', { name: /Rename this project/ }))
    const box = screen.getByLabelText('Project name')
    expect(box).toHaveValue('VCU Engine Firmware')
    await user.clear(box)
    await user.type(box, '  Brake ECU  ')
    await user.click(screen.getByRole('button', { name: /^Rename$/ }))
    await waitFor(() => expect(sent).toEqual([{ name: 'Brake ECU' }]))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('a blank name says why and is not sent; the same name is not sent either', async () => {
    const { sent, user } = setup()
    await openMenu(user)
    await user.click(await screen.findByRole('button', { name: /Rename this project/ }))
    const box = screen.getByLabelText('Project name')
    const rename = screen.getByRole('button', { name: /^Rename$/ })
    expect(rename).toBeDisabled()                                   // unchanged
    await user.clear(box)
    await user.type(box, '   ')
    expect(screen.getByRole('alert')).toHaveTextContent('A project needs a name.')
    expect(rename).toBeDisabled()
    await user.keyboard('{Enter}')
    expect(sent).toEqual([])
  })

  it('a refusal keeps the dialog open', async () => {
    const { sent, user } = setup({ refuse: true })
    await openMenu(user)
    await user.click(await screen.findByRole('button', { name: /Rename this project/ }))
    await user.type(screen.getByLabelText('Project name'), ' 2')
    await user.click(screen.getByRole('button', { name: /^Rename$/ }))
    await waitFor(() => expect(sent).toHaveLength(1))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('is not offered to someone who is not an admin of the project', async () => {
    const { user } = setup({ canRename: false })
    await openMenu(user)
    expect(await screen.findByText('Switch project')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Rename this project/ })).toBeNull()
  })
})
