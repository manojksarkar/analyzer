import { avatarPalette } from '../../lib/format'
import { cn } from '../../lib/cn'
import { Icon } from './Icon'

/**
 * A person's initials in their colour (stable per user id), or an empty dashed seat when there is
 * nobody — a document that needs a reviewer.
 */
export function Avatar({
  person, size = 24, title, className,
}: {
  person: { userId: string; name: string; initials: string } | null | undefined
  size?: number
  title?: string
  className?: string
}) {
  if (!person) {
    return (
      <span
        title={title}
        className={cn('inline-flex items-center justify-center rounded-full flex-shrink-0 border border-dashed border-outline-variant bg-white text-outline', className)}
        // eslint-disable-next-line no-restricted-syntax -- the avatar's size is the caller's
        style={{ width: size, height: size }}
      >
        <Icon name="person" size={Math.round(size * 0.55)} />
      </span>
    )
  }
  const pal = avatarPalette(person.userId)
  return (
    <span
      title={title ?? person.name}
      className={cn('inline-flex items-center justify-center rounded-full flex-shrink-0 font-sans font-bold', className)}
      // eslint-disable-next-line no-restricted-syntax -- avatar size and colours are data-driven
      style={{ width: size, height: size, background: pal.bg, color: pal.text, fontSize: Math.round(size * 0.38) }}
    >
      {person.initials}
    </span>
  )
}
