import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FailedRunBanner } from '../components/RunBanners'
import { failureParts } from '../helpers'
import type { AnalysisJob } from '../../../types'

/* #31: a run the engine stopped before the parse says why — a headline, its other reasons as
   `- ` lines, then the log. The banner showed the reasons' backticks and dashes as written. */

const MESSAGE = [
  'Stopped before the parse: component path `Layer1/Sample/Core` is not in the checkout',
  '- core `Core2` names no `compile_commands.json`',
  '',
  '[12:00:01] ERROR run: exit 2',
].join('\n')

describe('failureParts', () => {
  it('splits the headline, the engine reasons and the log', () => {
    expect(failureParts(MESSAGE)).toEqual({
      headline: 'Stopped before the parse: component path `Layer1/Sample/Core` is not in the checkout',
      reasons: ['core `Core2` names no `compile_commands.json`'],
      log: '[12:00:01] ERROR run: exit 2',
    })
  })

  it('a message with no reasons is a headline and a log; none at all still says something', () => {
    expect(failureParts('run.py exited with code 2.\nTraceback …')).toEqual({
      headline: 'run.py exited with code 2.', reasons: [], log: 'Traceback …',
    })
    expect(failureParts(null).headline).toBe('The analysis stopped with an error.')
  })
})

describe('FailedRunBanner', () => {
  it('shows the reasons as a list, their paths as code, and the log on request', async () => {
    const job = { status: 'failed', errorMessage: MESSAGE, branch: 'main', shortSha: 'b2e8d45', completedAt: null, versionTag: 'v2' } as unknown as AnalysisJob
    render(<FailedRunBanner job={job} isAdmin={false} onRerun={() => {}} />)
    expect(screen.getByText('Layer1/Sample/Core').tagName).toBe('CODE')
    expect(screen.getByRole('listitem')).toHaveTextContent('core Core2 names no compile_commands.json')
    expect(screen.queryByText(/ERROR run/)).not.toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: /Show details/ }))
    expect(screen.getByText(/ERROR run: exit 2/)).toBeInTheDocument()
    expect(screen.queryByText(/`/)).not.toBeInTheDocument()
  })
})
