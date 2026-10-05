import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { AddMemberDialog } from '../components/AddMemberDialog'
import type { TeamMember } from '../../../types'

/* Add member: search people by name or email (GET /users/search), pick one, add (A20); a whole
   address nobody has makes an account, whose temporary password is shown once. */

const PEOPLE = [
  { id: 'u1', name: 'Alice Müller', email: 'alice@aspice.dev', initials: 'AM' },
  { id: 'u7', name: 'Developer 1', email: 'dev1@aspice.dev', initials: 'D1' },
  { id: 'u8', name: 'Developer 2', email: 'dev2@aspice.dev', initials: 'D2' },
]
const alice: TeamMember = {
  id: 'm1', userId: 'u1', name: 'Alice Müller', initials: 'AM', email: 'alice@aspice.dev', role: 'admin',
  lastActive: '', avatarColor: '', avatarTextColor: '',
}

function setup() {
  const sent: Array<{ email: string; role: string }> = []
  server.use(
    http.get(`${API_BASE_URL}/users/search`, ({ request }) => {
      const q = (new URL(request.url).searchParams.get('q') ?? '').toLowerCase()
      return HttpResponse.json({
        users: PEOPLE.filter((u) => u.name.toLowerCase().includes(q) || u.email.includes(q)),
      })
    }),
    http.post(`${API_BASE_URL}/projects/p1/members/invite`, async ({ request }) => {
      const body = (await request.json()) as { email: string; role: string }
      sent.push(body)
      const isNew = !PEOPLE.some((u) => u.email === body.email)
      return HttpResponse.json({
        invite: { email: body.email, role: body.role },
        account: { created: isNew, temporary_password: isNew ? 'tmp-PASS-123' : null },
      }, { status: 201 })
    }),
  )
  const onClose = vi.fn()
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrap = (c: ReactNode) => <QueryClientProvider client={client}>{c}</QueryClientProvider>
  render(wrap(<AddMemberDialog projectId="p1" projectName="Demo" members={[alice]} onClose={onClose} />))
  return { sent, onClose, user: userEvent.setup() }
}

describe('AddMemberDialog', () => {
  it('finds people by name and by email; a member cannot be picked again', async () => {
    const { user } = setup()
    const box = screen.getByLabelText('Name or email')
    expect(await screen.findByText('dev2@aspice.dev')).toBeInTheDocument()     // before typing: everyone
    expect(screen.getByRole('button', { name: /Alice Müller/ })).toBeDisabled()
    expect(screen.getByText('Member')).toBeInTheDocument()

    await user.type(box, 'developer 1')                                          // by name
    await waitFor(() => expect(screen.queryByText('dev2@aspice.dev')).not.toBeInTheDocument())
    expect(screen.getByText('dev1@aspice.dev')).toBeInTheDocument()

    await user.clear(box)
    await user.type(box, 'dev2@')                                                // by email
    await waitFor(() => expect(screen.queryByText('dev1@aspice.dev')).not.toBeInTheDocument())
    expect(screen.getByText('dev2@aspice.dev')).toBeInTheDocument()
  })

  it('picks a person and adds them, with the role chosen', async () => {
    const { user, sent, onClose } = setup()
    await user.type(screen.getByLabelText('Name or email'), 'dev1')
    await user.click(await screen.findByRole('button', { name: /Developer 1/ }))
    expect(screen.queryByLabelText('Name or email')).not.toBeInTheDocument()     // the pick replaces the search
    await user.click(screen.getByLabelText('Admin'))
    await user.click(screen.getByRole('button', { name: /^Add$/ }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(sent).toEqual([{ email: 'dev1@aspice.dev', role: 'admin' }])
  })

  it('a whole address nobody has: offered as a new account, and its password is shown', async () => {
    const { user, sent, onClose } = setup()
    await user.type(screen.getByLabelText('Name or email'), 'New.Person@company.com')
    await user.click(await screen.findByRole('button', { name: /Add new\.person@company\.com/ }))
    await user.click(screen.getByRole('button', { name: /^Add$/ }))
    expect(await screen.findByText('Account created')).toBeInTheDocument()
    expect(screen.getByText('tmp-PASS-123')).toBeInTheDocument()
    expect(sent).toEqual([{ email: 'new.person@company.com', role: 'developer' }])
    expect(onClose).not.toHaveBeenCalled()
  })

  it('Add is off until someone is picked', async () => {
    setup()
    expect(screen.getByRole('button', { name: /^Add$/ })).toBeDisabled()
  })
})
