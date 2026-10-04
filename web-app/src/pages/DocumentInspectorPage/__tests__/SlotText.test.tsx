import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ApiError } from '../../../lib/http'
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

  it('a save that met a regenerating run: save again once it has finished — not "retry" now', async () => {
    const edit = api({ save: vi.fn().mockRejectedValue(new ApiError('busy', 409, 'VERSION_REGENERATING')) })
    renderWith(edit)
    const box = screen.getByRole('textbox')
    await userEvent.clear(box)
    await userEvent.type(box, 'Adds two.')
    await userEvent.tab()
    expect(await screen.findByText(/A run is regenerating this version — nothing was saved\. Save again once it has finished\./))
      .toBeInTheDocument()
    expect(screen.queryByText(/Leave the box again to retry/)).toBeNull()
    expect(box).toHaveValue('Adds two.')
  })

  it('a refusal (4xx) that would fail again is not invited to retry; a fault (5xx) is', async () => {
    const save = vi.fn()
      .mockRejectedValueOnce(new ApiError('A document that prints this text is approved', 409, 'DOCUMENT_APPROVED'))
      .mockRejectedValueOnce(new ApiError('Internal Server Error', 500))
    renderWith(api({ save }))
    const box = screen.getByRole('textbox')
    await userEvent.clear(box)
    await userEvent.type(box, 'Adds two.')
    await userEvent.tab()
    expect(await screen.findByText(/^Not saved: .*approved.*Your text is still here\.$/)).toBeInTheDocument()
    expect(screen.queryByText(/retry/i)).toBeNull()
    await userEvent.click(box)
    await userEvent.tab()
    expect(await screen.findByText(/Leave the box again to retry/)).toBeInTheDocument()
  })

  it('blocks a NUL character before sending, with a message under the box', async () => {
    const edit = api()
    renderWith(edit)
    const box = screen.getByRole('textbox')
    fireEvent.change(box, { target: { value: 'Adds\u0000 two.' } })
    fireEvent.blur(box)
    expect(await screen.findByText(/NUL character \(U\+0000\)/)).toBeInTheDocument()
    expect(edit.save).not.toHaveBeenCalled()
  })

  it('blocks a NUL character in a behaviour row’s bullets too', async () => {
    const edit = api()
    const row: Slot = { ...slot, kind: 'behaviourDescription', text: 'a\nb', llmText: 'a\nb', bullets: ['a', 'b'],
      functionId: 'F', externalCallerId: 'X' }
    render(<EditContext.Provider value={edit}><SlotText slot={row} display="a\nb" bullets={['a', 'b']} /></EditContext.Provider>)
    const box = screen.getByRole('textbox')
    fireEvent.change(box, { target: { value: 'a\nb\u0000c' } })
    fireEvent.blur(box)
    expect(await screen.findByText(/NUL character/)).toBeInTheDocument()
    expect(edit.save).not.toHaveBeenCalled()
  })

  // API spec §5: undone = isOverridden true, canUndo false, text === llmText. The page prints the
  // LLM's text again, so it is not a correction.
  const undone: Slot = { ...slot, isOverridden: true, canUndo: false, humanText: 'Adds.', updatedBy: 'u1',
    updatedAt: '2026-09-18T10:02:41Z' }

  it('an undone text is not marked Corrected — in edit mode or out of it', () => {
    renderWith(api(), undone)
    expect(screen.queryByText(/Corrected/)).toBeNull()
    expect(screen.queryByRole('button', { name: 'Undo' })).toBeNull()
    // Its record is kept: the history is still there.
    expect(screen.getByRole('button', { name: 'History' })).toBeInTheDocument()
  })

  it('an undone text has no corrected mark when read', () => {
    renderWith(api({ editing: false }), undone)
    expect(screen.queryByLabelText('Corrected by a reviewer')).toBeNull()
  })

  it('an orphan shows its old words greyed beside the text, never as the wording, and no Undo', () => {
    const orphan: Slot = { ...slot, text: 'Adds two integers.', llmText: 'Adds two integers.',
      humanText: 'Adds a and b, saturating.', isOverridden: false, isOrphaned: true, canUndo: false, updatedBy: 'u1' }
    renderWith(api(), orphan, 'Adds two integers.')
    expect(screen.getByRole('textbox')).toHaveValue('Adds two integers.')
    expect(screen.getByText('Your correction no longer applies (the code changed): «Adds a and b, saturating.»'))
      .toBeInTheDocument()
    expect(screen.queryByText(/^Corrected/)).toBeNull()
    expect(screen.queryByRole('button', { name: 'Undo' })).toBeNull()
  })
})
