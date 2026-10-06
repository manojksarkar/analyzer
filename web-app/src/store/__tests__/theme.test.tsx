import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { readTheme, THEME_KEY, useThemeStore } from '../theme'
import { ThemeToggle } from '../../components/shell/ThemeToggle'
import indexHtml from '../../../index.html?raw'

/* The theme: dark unless the user chose light; the choice is kept in localStorage `theme`; it is
   one attribute on <html> (index.css swaps the tokens); blocked storage changes nothing but the
   keeping. index.html applies it before React paints, the store after. */

const html = document.documentElement
const attr = () => html.getAttribute('data-theme')

/** A fresh page: the store reads storage as it does when the module loads. */
function reload() {
  useThemeStore.setState({ theme: readTheme() })
}

/** localStorage that throws on every call (private mode, site data blocked). */
function blockStorage() {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new DOMException('blocked', 'SecurityError') })
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('blocked', 'SecurityError') })
}

/** index.html's pre-paint script, run as the browser runs it. */
function runPrePaintScript() {
  const code = [...indexHtml.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]).join('\n')
  expect(code).toContain('data-theme')
  new Function(code)()
}

describe('theme', () => {
  beforeEach(() => {
    localStorage.clear()
    html.removeAttribute('data-theme')
    reload()
  })
  afterEach(() => vi.restoreAllMocks())

  it('is dark when nothing is saved', () => {
    expect(readTheme()).toBe('dark')
    expect(useThemeStore.getState().theme).toBe('dark')
    runPrePaintScript()
    expect(attr()).toBe('dark')
  })

  it('keeps the choice: saved, applied, and read back on the next load', () => {
    useThemeStore.getState().setTheme('light')
    expect(localStorage.getItem(THEME_KEY)).toBe('light')
    expect(attr()).toBe('light')

    html.removeAttribute('data-theme')
    reload()
    expect(useThemeStore.getState().theme).toBe('light')
    runPrePaintScript()
    expect(attr()).toBe('light')
  })

  it('ignores a saved value that is not a theme', () => {
    localStorage.setItem(THEME_KEY, 'sepia')
    reload()
    expect(useThemeStore.getState().theme).toBe('dark')
    runPrePaintScript()
    expect(attr()).toBe('dark')
  })

  it('still works when storage is blocked: dark, and a toggle lasts for the page', () => {
    blockStorage()
    reload()
    expect(useThemeStore.getState().theme).toBe('dark')
    runPrePaintScript()
    expect(attr()).toBe('dark')

    expect(() => useThemeStore.getState().toggleTheme()).not.toThrow()
    expect(useThemeStore.getState().theme).toBe('light')
    expect(attr()).toBe('light')
  })

  it('the top-bar button switches between the two and says which way it goes', async () => {
    const user = userEvent.setup()
    render(<ThemeToggle />)
    await user.click(screen.getByRole('button', { name: 'Switch to light theme' }))
    expect(attr()).toBe('light')
    expect(localStorage.getItem(THEME_KEY)).toBe('light')
    await user.click(screen.getByRole('button', { name: 'Switch to dark theme' }))
    expect(attr()).toBe('dark')
    expect(localStorage.getItem(THEME_KEY)).toBe('dark')
  })
})
