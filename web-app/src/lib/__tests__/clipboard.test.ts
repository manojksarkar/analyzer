import { afterEach, describe, expect, it, vi } from 'vitest'
import { copyText } from '../clipboard'

/* The office opens the app over plain http, where navigator.clipboard is undefined: a copy button
   did nothing there. The fallback copies through a hidden textarea. */

describe('copyText', () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

  it('uses the clipboard API in a secure context', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    vi.stubGlobal('isSecureContext', true)
    expect(await copyText('ver3')).toBe(true)
    expect(writeText).toHaveBeenCalledWith('ver3')
  })

  it('over plain http, copies through a textarea and leaves none behind', async () => {
    vi.stubGlobal('navigator', { ...navigator, clipboard: undefined })
    vi.stubGlobal('isSecureContext', false)
    const exec = vi.fn().mockReturnValue(true)
    Object.defineProperty(document, 'execCommand', { value: exec, configurable: true })
    expect(await copyText('pfc66bf4b')).toBe(true)
    expect(exec).toHaveBeenCalledWith('copy')
    expect(document.querySelector('textarea')).toBeNull()
  })

  it('says so when nothing could copy', async () => {
    vi.stubGlobal('navigator', { ...navigator, clipboard: undefined })
    vi.stubGlobal('isSecureContext', false)
    Object.defineProperty(document, 'execCommand', { value: () => { throw new Error('no') }, configurable: true })
    expect(await copyText('x')).toBe(false)
  })
})
