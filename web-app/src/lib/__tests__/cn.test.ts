import { describe, expect, it } from 'vitest'
import { cn } from '../cn'

describe('cn', () => {
  it("keeps a theme font size and a text colour - they are different properties", () => {
    expect(cn('mt-2 text-caption', 'text-outline')).toBe('mt-2 text-caption text-outline')
    expect(cn('text-on-surface-variant mt-1', 'text-caption font-mono')).toBe('text-on-surface-variant mt-1 text-caption font-mono')
    for (const size of ['text-micro', 'text-label', 'text-caption', 'text-body', 'text-title']) {
      expect(cn(size, 'text-secondary')).toBe(`${size} text-secondary`)
    }
  })

  it('still lets the last of two sizes, or of two colours, win', () => {
    expect(cn('text-label', 'text-body')).toBe('text-body')
    expect(cn('text-caption', 'text-xs')).toBe('text-xs')
    expect(cn('text-secondary', 'text-outline')).toBe('text-outline')
  })
})
