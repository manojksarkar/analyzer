import { afterEach, describe, expect, it } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import { CodeText } from '../CodeText'
import { ToastProvider, toast, useToastStore } from '../Toast'
import { LoadError } from '../../LoadError'

/* #31: the API's and the engine's messages write paths, keys and commands in backticks; the page
   showed the backticks. They read as code now — as text nodes, never as HTML. */

describe('CodeText', () => {
  it('shows each backticked part as code', () => {
    const { container } = render(<p><CodeText text="Run `analyzer.py reexport` for `Layer1.Core`." /></p>)
    expect([...container.querySelectorAll('code')].map((c) => c.textContent)).toEqual(['analyzer.py reexport', 'Layer1.Core'])
    expect(container.textContent).toBe('Run analyzer.py reexport for Layer1.Core.')
  })

  it('leaves an unpaired backtick as written', () => {
    const { container } = render(<p><CodeText text="a `b` c ` d" /></p>)
    expect([...container.querySelectorAll('code')].map((c) => c.textContent)).toEqual(['b'])
    expect(container.textContent).toBe('a b c ` d')
  })

  it('never renders markup', () => {
    const { container } = render(<p><CodeText text="<b>x</b> `<i>y</i>`" /></p>)
    expect(container.querySelector('b')).toBeNull()
    expect(container.querySelector('i')).toBeNull()
    expect(container.querySelector('code')).toHaveTextContent('<i>y</i>')
  })
})

describe('messages from the API', () => {
  afterEach(() => useToastStore.setState({ toasts: [] }))

  it('a toast shows its backticked parts as code', async () => {
    render(<ToastProvider />)
    act(() => { toast.error('Update refused', 'No documents in this version. `Generate` makes them.') })
    expect((await screen.findByText('Generate')).tagName).toBe('CODE')
  })

  it('a failed read shows its backticked parts as code', () => {
    render(<LoadError what="the slots" error={new Error('Copy `slotKey` from R11')} onRetry={() => {}} />)
    expect(screen.getByText('slotKey').tagName).toBe('CODE')
  })
})
