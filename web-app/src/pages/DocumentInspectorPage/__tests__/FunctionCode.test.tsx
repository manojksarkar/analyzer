import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { FunctionCode } from '../components/FunctionCode'

/* NW-7: a function's own lines of code under its flowchart, read only when opened. */

const SOURCE = `${API_BASE_URL}/projects/p1/versions/v1/functions/source`

function mount() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <FunctionCode projectId="p1" versionId="v1" functionId="Math|Utils|scale" />
    </QueryClientProvider>,
  )
}

describe('FunctionCode', () => {
  it('reads the code only when opened, and numbers its lines from the function\'s first', async () => {
    let asked = ''
    server.use(http.get(SOURCE, ({ request }) => {
      asked = new URL(request.url).searchParams.get('function_id') ?? ''
      return HttpResponse.json({ function_id: 'Math|Utils|scale', file: 'src/util.cpp', start_line: 3,
        end_line: 4, lines: ['int scale(int a, int b) {', '}'], truncated: false })
    }))
    mount()
    expect(screen.queryByText(/util\.cpp/)).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /show code/i }))
    expect(await screen.findByText('src/util.cpp · lines 3–4')).toBeInTheDocument()
    expect(asked).toBe('Math|Utils|scale')
    expect(screen.getByText('int scale(int a, int b) {')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /hide code/i })).toHaveAttribute('aria-expanded', 'true')
  })

  it('says why when the version\'s code is not on the server', async () => {
    server.use(http.get(SOURCE, () => HttpResponse.json({ detail: { code: 'SOURCE_NOT_HERE', status: 409,
      message: 'The code of this version is not on this server.' } }, { status: 409 })))
    mount()
    await userEvent.click(screen.getByRole('button', { name: /show code/i }))
    expect(await screen.findByText(/not on this server/)).toBeInTheDocument()
  })

  it('says when the function was cut', async () => {
    server.use(http.get(SOURCE, () => HttpResponse.json({ function_id: 'f', file: 'a.cpp', start_line: 1,
      end_line: 900, lines: ['x'], truncated: true })))
    mount()
    await userEvent.click(screen.getByRole('button', { name: /show code/i }))
    expect(await screen.findByText(/goes on to line 900/)).toBeInTheDocument()
  })
})
