import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { useAuthStore } from '../../../store/auth'
import { useToastStore } from '../../../components/ui/Toast'
import project from '../../../test/fixtures/captured/project.json'
import members from '../../../test/fixtures/captured/members.json'
import { TeamPage } from '..'
import { asksBeforeRoleChange, isLastAdmin } from '../helpers'
import type { TeamMember } from '../../../types'

/* The project's only active admin is neither demoted nor removed (the API refuses: 409
   LAST_ADMIN); removing a member, or demoting yourself, is asked first. Alice (u1) is the
   fixture's only admin; the signed-in user is Alice. */

type ApiMember = (typeof members.members)[number]
const LAST_ADMIN = "This is the project's only admin. Make someone else an admin first."

function setup(list: ApiMember[] = members.members, refuse = false) {
  const sent: string[] = []
  const conflict = () => HttpResponse.json(
    { detail: { code: 'LAST_ADMIN', status: 409, message: LAST_ADMIN } }, { status: 409 })
  server.use(
    http.get(`${API_BASE_URL}/projects/p1`, () => HttpResponse.json(project)),
    http.get(`${API_BASE_URL}/projects/p1/members`, () => HttpResponse.json({ members: list })),
    http.get(`${API_BASE_URL}/projects/p1/members/pending`, () => HttpResponse.json({ pending: [] })),
    http.patch(`${API_BASE_URL}/projects/p1/members/:uid/role`, async ({ params, request }) => {
      const { role } = (await request.json()) as { role: string }
      sent.push(`role ${params.uid} ${role}`)
      if (refuse) return conflict()
      return HttpResponse.json({ member: { ...list.find((m) => m.user_id === params.uid)!, role } })
    }),
    http.delete(`${API_BASE_URL}/projects/p1/members/:uid`, ({ params }) => {
      sent.push(`remove ${params.uid}`)
      return refuse ? conflict() : new HttpResponse(null, { status: 204 })
    }),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/projects/p1/team']}>
        <Routes>
          <Route path="/projects/:projectId/team" element={<TeamPage />} />
          <Route path="/projects" element={<p>Projects list</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { sent, user: userEvent.setup() }
}

const asAdmin = (m: ApiMember) => ({ ...m, role: 'admin' })

describe('TeamPage', { timeout: 30_000 }, () => {
  beforeEach(() => {
    useAuthStore.setState({ user: { id: 'u1', name: 'Alice Müller', email: 'alice@aspice.dev', initials: 'AM' } })
    useToastStore.setState({ toasts: [] })
  })
  afterEach(() => useAuthStore.setState({ user: null }))

  it("does not offer Developer or Remove for the only admin, and says why", async () => {
    const { user } = setup()
    const remove = await screen.findByRole('button', { name: 'Remove Alice Müller' })
    expect(remove).toBeDisabled()
    expect(remove).toHaveAttribute('title', LAST_ADMIN)
    expect(screen.getByRole('button', { name: 'Remove Bob Kumar' })).toBeEnabled()

    await user.click(screen.getByRole('button', { name: 'Role of Alice Müller: Admin' }))
    const developer = within(screen.getByRole('menu')).getByRole('menuitem', { name: 'Developer' })
    expect(developer).toBeDisabled()
    expect(developer).toHaveAttribute('title', LAST_ADMIN)
  })

  it('asks before removing a member; Cancel removes nobody', async () => {
    const { sent, user } = setup()
    await user.click(await screen.findByRole('button', { name: 'Remove Bob Kumar' }))
    let dialog = await screen.findByRole('dialog', { name: 'Remove Bob Kumar?' })
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(sent).toEqual([])

    await user.click(screen.getByRole('button', { name: 'Remove Bob Kumar' }))
    dialog = await screen.findByRole('dialog', { name: 'Remove Bob Kumar?' })
    await user.click(within(dialog).getByRole('button', { name: /Remove/ }))
    await waitFor(() => expect(sent).toEqual(['remove u2']))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('asks before demoting yourself, not before demoting another admin', async () => {
    const two = [members.members[0], asAdmin(members.members[1]), members.members[2]]
    const { sent, user } = setup(two)
    await user.click(await screen.findByRole('button', { name: 'Role of Bob Kumar: Admin' }))
    await user.click(within(screen.getByRole('menu')).getByRole('menuitem', { name: 'Developer' }))
    await waitFor(() => expect(sent).toEqual(['role u2 developer']))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Role of Alice Müller: Admin' }))
    await user.click(within(screen.getByRole('menu')).getByRole('menuitem', { name: 'Developer' }))
    const dialog = await screen.findByRole('dialog', { name: 'Make yourself a Developer?' })
    expect(sent).toEqual(['role u2 developer'])
    await user.click(within(dialog).getByRole('button', { name: /Make me a Developer/ }))
    await waitFor(() => expect(sent).toEqual(['role u2 developer', 'role u1 developer']))
  })

  it("shows the API's message when it refuses anyway", async () => {
    // Bob looks like a second admin here, but the server knows better.
    const two = [members.members[0], asAdmin(members.members[1]), members.members[2]]
    const { user } = setup(two, true)
    await user.click(await screen.findByRole('button', { name: 'Remove Bob Kumar' }))
    const dialog = await screen.findByRole('dialog', { name: 'Remove Bob Kumar?' })
    await user.click(within(dialog).getByRole('button', { name: /Remove/ }))
    await waitFor(() => expect(useToastStore.getState().toasts).toEqual([
      expect.objectContaining({ title: 'Could not remove member', description: LAST_ADMIN, variant: 'error' }),
    ]))
  })
})

describe('team helpers', () => {
  const m = (id: string, role: 'admin' | 'developer', pending = false): TeamMember => ({
    id, userId: `u${id}`, name: id, initials: id, email: '', role, lastActive: '', avatarColor: '',
    avatarTextColor: '', pending,
  })

  it('the last admin is the only active one; a pending admin does not count', () => {
    const a = m('a', 'admin')
    expect(isLastAdmin(a, [a, m('b', 'developer')])).toBe(true)
    expect(isLastAdmin(a, [a, m('b', 'admin', true)])).toBe(true)
    expect(isLastAdmin(a, [a, m('b', 'admin')])).toBe(false)
    expect(isLastAdmin(m('b', 'developer'), [a, m('b', 'developer')])).toBe(false)
  })

  it('only taking your own admin role away asks first', () => {
    expect(asksBeforeRoleChange(m('a', 'admin'), 'developer', 'ua')).toBe(true)
    expect(asksBeforeRoleChange(m('a', 'admin'), 'developer', 'ub')).toBe(false)
    expect(asksBeforeRoleChange(m('a', 'developer'), 'admin', 'ua')).toBe(false)
    expect(asksBeforeRoleChange(m('a', 'admin'), 'developer', '')).toBe(false)
  })
})
