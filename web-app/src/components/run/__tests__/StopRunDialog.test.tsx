import { describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StopRunDialog } from '../StopRunDialog'

/* One dialog for every Stop / Cancel Job: what stopping costs depends on the job's mode. */

describe('StopRunDialog', () => {
  it("a version's own run: the version goes with everything made so far", async () => {
    const onConfirm = vi.fn()
    const onClose = vi.fn()
    render(<StopRunDialog job={{ id: 'job9', mode: 'auto' }} versionTag="v2" busy={false}
                          onConfirm={onConfirm} onClose={onClose} />)
    const dialog = screen.getByRole('dialog', { name: 'Cancel this generation?' })
    expect(within(dialog).getByText(/this version is removed/)).toBeInTheDocument()
    expect(within(dialog).getByText('Job job9 · version v2')).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(within(dialog).getByRole('button', { name: 'Keep running' }))
    expect(onClose).toHaveBeenCalledOnce()
    expect(onConfirm).not.toHaveBeenCalled()
    await user.click(within(dialog).getByRole('button', { name: 'Cancel generation' }))
    expect(onConfirm).toHaveBeenCalledOnce()
  })

  it.each(['export', 'reexport'])('a %s job adds documents: what is finished stays', (mode) => {
    render(<StopRunDialog job={{ id: 'job9', mode }} busy={false} onConfirm={() => {}} onClose={() => {}} />)
    const dialog = screen.getByRole('dialog', { name: 'Stop making these documents?' })
    expect(within(dialog).getByText(/Components already finished keep their documents/)).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Stop' })).toBeInTheDocument()
  })
})
