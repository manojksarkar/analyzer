import { afterEach, describe, expect, it } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { useAuthStore } from '../../../store/auth'
import { NotificationBell } from '../NotificationBell'

/* The bell's Word file notifications (WORD_FILE_UPDATES §4.7; A16): an update written, and one
   that failed — each with its own mark, opening its document (its banner says the file's state). */

const note = (id: string, type: string, message: string, documentId: string | null) => ({
  id, project_id: 'p1', type, message, document_id: documentId, read_at: null, created_at: new Date().toISOString(),
})

function Where() {
  const l = useLocation()
  return <p data-testid="where">{l.pathname + l.search}</p>
}

function setup() {
  useAuthStore.setState({ isAuthenticated: true, user: { id: 'u2', email: 'developer@company.com', name: 'Developer B' } as never })
  const read: string[] = []
  server.use(
    http.get(`${API_BASE_URL}/notifications`, () => HttpResponse.json({ notifications: [
      note('n1', 'word_files_updated', 'Word files updated: Brake Controller in v1.2.0.', 'docc1442'),
      note('n2', 'word_files_update_failed', 'Update failed: HVAC Ctrl in v1.2.0 — flowchart pictures could not be drawn.', null),
    ] })),
    http.patch(`${API_BASE_URL}/notifications/:id/read`, ({ params }) => { read.push(String(params.id)); return HttpResponse.json({}) }),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/']}>
        <NotificationBell />
        <Routes><Route path="*" element={<Where />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { read, user: userEvent.setup() }
}

afterEach(() => useAuthStore.setState({ isAuthenticated: false, user: null }))

describe('NotificationBell — Word file updates', () => {
  it('lists both kinds with their own marks; a written one opens its document', async () => {
    const { read, user } = setup()
    await user.click(await screen.findByRole('button', { name: /Notifications \(2 unread\)/ }))
    const done = screen.getByText('Word files updated: Brake Controller in v1.2.0.').closest('button') as HTMLElement
    const failed = screen.getByText(/^Update failed: HVAC Ctrl in v1\.2\.0/).closest('button') as HTMLElement
    expect(done.querySelector('.material-symbols-outlined')?.textContent).toBe('task_alt')
    expect(failed.querySelector('.material-symbols-outlined')?.textContent).toBe('error')
    await user.click(done)
    await waitFor(() => expect(read).toEqual(['n1']))
    // Its document, not its Review tab: the banner there says the Word file's state.
    expect(screen.getByTestId('where')).toHaveTextContent('/projects/p1/documents/docc1442')
    expect(screen.getByTestId('where').textContent).not.toMatch(/tab=review/)
  })
})
