import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { RunAnalysisModal } from '../components/RunAnalysisModal'
import { versionNameProblem } from '../helpers'
import type { Commit, Project, Version } from '../../../types'

/* Run Analysis: a version needs a name nobody in the project has (the API refuses an empty one,
   and a duplicate with VERSION_EXISTS), so Start says so before the click. The dialog keeps its
   input on a stray click beside it; Esc and Close still close it. */

const project = { id: 'p1', name: 'Demo', defaultBranch: 'main', architectureLayers: [] } as unknown as Project
const commits: Commit[] = [
  { sha: 'b2e8d45aa', shortSha: 'b2e8d45', message: 'Fix', author: 'A', relativeTime: '1d', branch: 'main', pageState: 'never' },
]
const versions = [
  { id: 'ver2', tag: 'v1.2.0', sha: 'b2e8d45aa', shortSha: 'b2e8d45', description: '' },
  { id: 'ver1', tag: 'v1.1.0', sha: 'a1a1a1a1a', shortSha: 'a1a1a1a', description: '' },
] as unknown as Version[]

function setup(p: Project = project) {
  const onStart = vi.fn()
  const onClose = vi.fn()
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <RunAnalysisModal project={p} commits={commits} commitsLoading={false} versions={versions}
                        submitting={false} onClose={onClose} onStart={onStart} />
    </QueryClientProvider>,
  )
  const dialog = screen.getByRole('dialog', { name: 'Run Analysis' })
  return {
    onStart, onClose, dialog, user: userEvent.setup(),
    name: within(dialog).getByRole('textbox', { name: 'Version name' }),
    start: within(dialog).getByRole('button', { name: /START ANALYSIS/ }),
    // The second select: Compare against (the first is the commit)
    compare: () => within(dialog).getAllByRole('combobox')[1],
  }
}

describe('RunAnalysisModal', () => {
  it('suggests the next version and starts it', async () => {
    const { name, start, onStart, user } = setup()
    expect(name).toHaveValue('v1.3.0')
    expect(start).toBeEnabled()
    await user.click(start)
    expect(onStart).toHaveBeenCalledWith(expect.objectContaining({ commit_sha: 'b2e8d45aa', version_tag: 'v1.3.0' }))
  })

  it('an empty name or one the project has keeps Start off, and says why', async () => {
    const { name, start, dialog, onStart, user } = setup()
    await user.clear(name)
    expect(start).toBeDisabled()
    expect(start).toHaveAttribute('title', 'Name the version.')
    expect(within(dialog).getByText('Name the version.')).toBeInTheDocument()

    await user.type(name, 'v1.1.0')
    expect(start).toBeDisabled()
    expect(within(dialog).getByText('v1.1.0 already exists in this project. Choose another name.')).toBeInTheDocument()
    expect(name).toHaveAttribute('aria-invalid', 'true')

    await user.type(name, '-rc1')
    expect(start).toBeEnabled()
    expect(name).not.toHaveAttribute('aria-invalid')
    expect(onStart).not.toHaveBeenCalled()
  })

  it('a click beside it keeps the input; Esc closes it', async () => {
    const { onClose, user } = setup()
    fireEvent.pointerDown(document.body)
    expect(onClose).not.toHaveBeenCalled()
    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledOnce()
  })
})

/* An incremental run -- one compared against a version -- starts from the components that version
   made documents for, not every component: a whole project's run takes hours. */
describe('RunAnalysisModal, compared against a version', () => {
  const layered = { ...project, architectureLayers: [
    { name: 'Layer1', groups: [{ name: 'G', components: [{ name: 'Math' }, { name: 'Util' }] }] },
    { name: 'Layer2', groups: [{ name: 'H', components: [{ name: 'Gpio' }, { name: 'Uart' }] }] },
  ] } as unknown as Project
  const comp = (id: string, docs: number) => ({
    component: id, layer: id.split('.')[0], name: id.split('.')[1], state: docs ? 'generated' : 'not_requested',
    in_model: true, layer_parsed: true, group: null, error: null,
    documents: Array.from({ length: docs }, (_, i) => ({ id: `${id}-d${i}`, process: i ? 'SWE.4' : 'SWE.3', status: 'in_review' })),
  })
  const baseline = () => server.use(http.get(`${API_BASE_URL}/projects/p1/versions/ver1/components`, () => HttpResponse.json({
    version_id: 'ver1', components: [comp('Layer1.Math', 2), comp('Layer1.Util', 0), comp('Layer2.Gpio', 2), comp('Layer2.Uart', 0)],
    counts: { generated: 2, not_requested: 2 }, run: null, job: null, resume_action: 'nothing',
  })))

  it('ticks the components the version has documents for, and says so', async () => {
    baseline()
    const { dialog, start, onStart, user, compare } = setup(layered)
    await user.selectOptions(compare(), 'ver1')
    await within(dialog).findByText('Starts with the 2 components v1.1.0 has documents for.')
    expect(within(dialog).getByText('2 of 4 components')).toBeInTheDocument()   // the Advanced options row
    await user.click(start)
    expect(onStart).toHaveBeenCalledWith(expect.objectContaining({
      reference_version_id: 'ver1', scope: { type: 'component', names: ['Layer1.Math', 'Layer2.Gpio'] },
    }))
  })

  it('back to None, every component again: the whole project', async () => {
    baseline()
    const { dialog, start, onStart, user, compare } = setup(layered)
    await user.selectOptions(compare(), 'ver1')
    await within(dialog).findByText(/Starts with the 2 components/)
    await user.selectOptions(compare(), '')
    await waitFor(() => expect(within(dialog).queryByText(/Starts with/)).not.toBeInTheDocument())
    await user.click(start)
    expect(onStart).toHaveBeenCalledWith(expect.objectContaining({ scope: undefined, reference_version_id: undefined }))
  })

  it("someone's own ticks stand", async () => {
    baseline()
    const { dialog, start, onStart, user, compare } = setup(layered)
    await user.selectOptions(compare(), 'ver1')
    await within(dialog).findByText(/Starts with the 2 components/)
    await user.click(within(dialog).getByRole('button', { name: /Advanced options/ }))
    await user.click(within(dialog).getByRole('button', { name: 'All' }))
    expect(within(dialog).queryByText(/Starts with/)).not.toBeInTheDocument()
    await user.click(start)
    expect(onStart).toHaveBeenCalledWith(expect.objectContaining({ reference_version_id: 'ver1', scope: undefined }))
  })
})

describe('versionNameProblem', () => {
  it('needs a name, not taken in the project (exactly, after trimming)', () => {
    expect(versionNameProblem('  ', versions)).toBe('Name the version.')
    expect(versionNameProblem(' v1.2.0 ', versions)).toMatch(/already exists/)
    expect(versionNameProblem('V1.2.0', versions)).toBeNull()
    expect(versionNameProblem('v2', undefined)).toBeNull()
  })
})
