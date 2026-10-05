import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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

function setup() {
  const onStart = vi.fn()
  const onClose = vi.fn()
  render(
    <RunAnalysisModal project={project} commits={commits} commitsLoading={false} versions={versions}
                      submitting={false} onClose={onClose} onStart={onStart} />,
  )
  const dialog = screen.getByRole('dialog', { name: 'Run Analysis' })
  return {
    onStart, onClose, dialog, user: userEvent.setup(),
    name: within(dialog).getByRole('textbox', { name: 'Version name' }),
    start: within(dialog).getByRole('button', { name: /START ANALYSIS/ }),
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

describe('versionNameProblem', () => {
  it('needs a name, not taken in the project (exactly, after trimming)', () => {
    expect(versionNameProblem('  ', versions)).toBe('Name the version.')
    expect(versionNameProblem(' v1.2.0 ', versions)).toMatch(/already exists/)
    expect(versionNameProblem('V1.2.0', versions)).toBeNull()
    expect(versionNameProblem('v2', undefined)).toBeNull()
  })
})
