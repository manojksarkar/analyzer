import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import type { FlowchartEntry } from '../../../types'
import { FunctionCode } from '../components/FunctionCode'

/* NW-7 (docs/ui-mockups/documents.html#code): a function's flowchart and its code side by side, in a
   dialog View code opens; the code is read only then. */

const SOURCE = `${API_BASE_URL}/projects/p1/versions/v1/functions/source`
const chart = { label: 'scale', status: 'drawn', imageUrl: '/fc/scale.svg', width: 200, height: 300, boxes: 4,
  flowchartId: 'f1', editable: true } as unknown as FlowchartEntry

function mount() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <FunctionCode projectId="p1" versionId="v1" functionId="Math|Utils|scale" title="Utils-scale" flowcharts={[chart]} />
    </QueryClientProvider>,
  )
}

async function openView() {
  await userEvent.click(screen.getByRole('button', { name: /view code/i }))
  return screen.findByRole('dialog', { name: 'Utils-scale — flowchart and code' })
}

describe('FunctionCode', () => {
  it('reads nothing until opened; then the flowchart and the numbered code side by side', async () => {
    let asked = ''
    server.use(http.get(SOURCE, ({ request }) => {
      asked = new URL(request.url).searchParams.get('function_id') ?? ''
      return HttpResponse.json({ function_id: 'Math|Utils|scale', file: 'src/util.cpp', start_line: 3,
        end_line: 4, lines: ['int scale(int a, int b) {', '}'], truncated: false })
    }))
    mount()
    expect(asked).toBe('')
    const dialog = await openView()
    expect(await within(dialog).findByText('src/util.cpp · lines 3–4')).toBeInTheDocument()
    expect(asked).toBe('Math|Utils|scale')
    expect(within(dialog).getByRole('region', { name: 'Flowchart' })).toContainElement(within(dialog).getByAltText('Flowchart of scale'))
    const code = within(dialog).getByRole('region', { name: 'Code' })
    expect(within(code).getByText('int scale(int a, int b) {')).toBeInTheDocument()
    expect(within(code).getByText('3')).toBeInTheDocument()
  })

  it('says why when the version\'s code is not on the server', async () => {
    server.use(http.get(SOURCE, () => HttpResponse.json({ detail: { code: 'SOURCE_NOT_HERE', status: 409,
      message: 'The code of this version is not on this server.' } }, { status: 409 })))
    mount()
    const dialog = await openView()
    expect(await within(dialog).findByText(/not on this server/)).toBeInTheDocument()
  })

  it('says when the function was cut', async () => {
    server.use(http.get(SOURCE, () => HttpResponse.json({ function_id: 'f', file: 'a.cpp', start_line: 1,
      end_line: 900, lines: ['x'], truncated: true })))
    mount()
    const dialog = await openView()
    expect(await within(dialog).findByText(/goes on to line 900/)).toBeInTheDocument()
  })
})
