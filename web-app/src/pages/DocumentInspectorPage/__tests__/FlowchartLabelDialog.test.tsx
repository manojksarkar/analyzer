import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { FlowchartLabelDialog } from '../components/FlowchartLabelDialog'
import type { FlowchartEntry } from '../../../types'

/* One flowchart's labels (R7 reads, R8 saves): a NUL character is stopped before sending (the
   API answers 422), an undone label is not "corrected", and an orphan's old words are shown
   greyed, never as the label (API spec §5, §12, §13). */

const FC = 'C|U|f|int'
const node = (id: string, over: Record<string, unknown> = {}) => ({
  slotKind: 'nodeLabel', slotKey: `${FC}\u0001${id}`, flowchartId: FC, nodeId: id,
  text: `Box ${id}`, llmText: `Box ${id}`, humanText: null,
  isOverridden: false, isOrphaned: false, canUndo: false, updatedBy: null, updatedAt: null, ...over,
})

const chart: FlowchartEntry = {
  label: 'int f()', status: 'drawn', imageUrl: null, width: null, height: null, boxes: 3,
  flowchartId: FC, editable: true,
}

function setup() {
  const saved: unknown[] = []
  server.use(
    http.get(`${API_BASE_URL}/projects/p1/versions/v1/flowcharts/labels`, () => HttpResponse.json({
      flowchartId: FC, functionName: 'f', graphAvailable: true, dot: '',
      labels: [
        node('n1'),
        // Undone: the record stays, isOverridden too; the picture carries the LLM's text again.
        node('n2', { isOverridden: true, humanText: 'Box n2', updatedBy: 'u1' }),
        // Orphan: written for an earlier numbering of the nodes — kept, not applied.
        node('n3', { isOrphaned: true, humanText: 'Check the old flag', updatedBy: 'u1' }),
      ],
    })),
    http.put(`${API_BASE_URL}/projects/p1/versions/v1/flowcharts/labels`, async ({ request }) => {
      saved.push(await request.json())
      return HttpResponse.json({ flowchartId: FC, labels: [] })
    }),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <FlowchartLabelDialog chart={chart} projectId="p1" versionId="v1" locked={false}
        userName={() => 'Alice'} onClose={vi.fn()} />
    </QueryClientProvider>,
  )
  return saved
}

describe('FlowchartLabelDialog', () => {
  it('stops a label with a NUL character before sending, and says which box has it', async () => {
    const saved = setup()
    const box = await screen.findByRole('textbox', { name: 'Label of box 1' })
    fireEvent.change(box, { target: { value: 'Box\u0000 n1' } })
    expect(screen.getByText(/Contains a NUL character \(U\+0000\)/)).toBeInTheDocument()
    expect(screen.getByText(/A label contains a NUL character/)).toBeInTheDocument()
    const save = screen.getByRole('button', { name: /Save 1 label/ })
    expect(save).toBeDisabled()
    fireEvent.click(save)
    expect(saved).toHaveLength(0)
  })

  it('an undone label reads "generated", not "corrected"; an orphan shows its old words greyed', async () => {
    setup()
    await screen.findByRole('textbox', { name: 'Label of box 3' })
    expect(screen.queryByText(/^corrected/)).toBeNull()
    expect(screen.getAllByText('generated')).toHaveLength(3)
    expect(screen.getByText('Your correction no longer applies (the code changed): «Check the old flag»')).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Label of box 3' })).toHaveValue('Box n3')
    expect(screen.queryByRole('button', { name: 'Undo' })).toBeNull()
  })
})
