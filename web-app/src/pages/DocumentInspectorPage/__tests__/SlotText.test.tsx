import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SlotText } from '../components/SlotText'
import { EditContext, type EditApi } from '../editContext'
import type { Slot } from '../../../types'

const slot: Slot = {
  kind: 'description', key: 'C|U|f|int', text: 'Adds.', llmText: 'Adds.', humanText: null,
  isOverridden: false, isOrphaned: false, canUndo: false, updatedBy: null, updatedAt: null,
}

function api(over: Partial<EditApi> = {}): EditApi {
  return {
    editing: true, locked: false, projectId: 'p1', versionId: 'v1',
    save: vi.fn().mockResolvedValue(undefined), undo: vi.fn(), openFlowchart: vi.fn(),
    labelsLocked: null,
    userName: (id) => (id === 'u1' ? 'Alice Chen' : ''),
    ...over,
  }
}

function renderWith(edit: EditApi, s: Slot = slot, display = 'Adds.') {
  return render(<EditContext.Provider value={edit}><SlotText slot={s} display={display} /></EditContext.Provider>)
}

describe('SlotText (a text a reviewer can correct)', () => {
  it('reads as the document prints it outside edit mode, marked when corrected', () => {
    const corrected = { ...slot, isOverridden: true, humanText: 'Adds a.', text: 'Adds a.', updatedBy: 'u1' }
    renderWith(api({ editing: false }), corrected, 'Adds a.')
    expect(screen.queryByRole('textbox')).toBeNull()
    expect(screen.getByText('Adds a.')).toBeInTheDocument()
    expect(screen.getByLabelText('Corrected by a reviewer')).toHaveAttribute('title', expect.stringContaining('Alice Chen'))
  })

  it('saves when you leave the box', async () => {
    const edit = api()
    renderWith(edit)
    const box = screen.getByRole('textbox', { name: 'Correct this text' })
    await userEvent.clear(box)
    await userEvent.type(box, 'Adds two numbers.')
    await userEvent.tab()
    expect(edit.save).toHaveBeenCalledWith(slot, 'Adds two numbers.')
  })

  it('saves on Enter, and Esc cancels', async () => {
    const edit = api()
    renderWith(edit)
    const box = screen.getByRole('textbox')
    await userEvent.clear(box)
    await userEvent.type(box, 'Changed{Escape}')
    expect(edit.save).not.toHaveBeenCalled()
    expect(box).toHaveValue('Adds.')
    await userEvent.clear(box)
    await userEvent.type(box, 'Again{Enter}')
    expect(edit.save).toHaveBeenCalledWith(slot, 'Again')
  })

  it('does not save an empty text', async () => {
    const edit = api()
    renderWith(edit)
    await userEvent.clear(screen.getByRole('textbox'))
    await userEvent.tab()
    expect(edit.save).not.toHaveBeenCalled()
    expect(screen.getByText(/can’t be empty/)).toBeInTheDocument()
  })

  it('offers Undo exactly when the slot can be undone', async () => {
    const edit = api()
    const corrected = { ...slot, isOverridden: true, canUndo: true, humanText: 'Adds a.', text: 'Adds a.', updatedBy: 'u1' }
    renderWith(edit, corrected, 'Adds a.')
    expect(screen.getByText(/Corrected by Alice Chen/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Undo' }))
    expect(edit.undo).toHaveBeenCalledWith(corrected)
  })

  it('is read-only while a run or re-export is going', () => {
    renderWith(api({ locked: true }))
    expect(screen.getByRole('textbox')).toHaveAttribute('readonly')
  })
})
