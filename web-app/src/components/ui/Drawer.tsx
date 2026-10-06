import { useRef, type ReactNode } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { cn } from '../../lib/cn'
import { Icon } from './Icon'

interface DrawerProps {
  open: boolean
  onClose: () => void
  /** The heading; it names the dialog. */
  title: string
  /** One line under the title; it describes the dialog. */
  description?: ReactNode
  /** Under the title row, inside the header (search, filters, a legend). */
  header?: ReactNode
  /** Pinned to the bottom. */
  footer?: ReactNode
  children: ReactNode
  className?: string
}

/**
 * A sheet from the right edge, full height (`min(640px, 100%)` wide), over a scrim — the Modal's
 * twin for a list too long for a dialog. Like the Modal: Esc, a click on the scrim and the X close
 * it; focus moves in, stays in, and returns to what opened it. The body scrolls; header and
 * footer stay.
 */
export function Drawer({ open, onClose, title, description, header, footer, children, className }: DrawerProps) {
  // What had focus when it opened: focus goes back there when it closes. (Radix returns it to a
  // Dialog.Trigger only, and the drawer is opened by its caller's own button.)
  const opener = useRef<HTMLElement | null>(null)
  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay data-scrim className="fixed inset-0 z-50 bg-inverse/32 animate-in fade-in-0" />
        <Dialog.Content
          // Radix hides the rest of the page from assistive tech; say it is modal too.
          aria-modal="true"
          onOpenAutoFocus={(e) => {
            opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
            // An element marked `data-autofocus` (a search box) takes focus, else the first one.
            const first = (e.currentTarget as HTMLElement | null)?.querySelector<HTMLElement>('[data-autofocus]')
            if (first) {
              e.preventDefault()
              first.focus()
            }
          }}
          onCloseAutoFocus={(e) => {
            e.preventDefault()
            opener.current?.focus()
          }}
          // Radix names the description itself when there is one; none, and it must not ask.
          {...(description ? {} : { 'aria-describedby': undefined })}
          className={cn(
            'fixed z-50 inset-y-0 right-0 w-[min(640px,100%)] bg-surface-container-lowest flex flex-col',
            'shadow-[-8px_0_24px_rgba(4,22,39,.14)] focus:outline-none',
            className,
          )}
        >
          <header className="px-6 pt-[18px] pb-3.5 border-b border-hairline">
            <div className="flex items-start gap-3">
              <div className="flex-1 min-w-0">
                <Dialog.Title className="text-lg font-semibold text-on-surface">{title}</Dialog.Title>
                {description && (
                  <Dialog.Description className="text-xs text-outline mt-0.5">{description}</Dialog.Description>
                )}
              </div>
              <Dialog.Close asChild>
                <button
                  type="button"
                  aria-label="Close"
                  className="w-8 h-8 flex-shrink-0 rounded-[6px] flex items-center justify-center text-on-surface-variant hover:bg-surface-container transition-colors"
                >
                  <Icon name="close" size={20} />
                </button>
              </Dialog.Close>
            </div>
            {header}
          </header>
          <div className="flex-1 min-h-0 overflow-y-auto">{children}</div>
          {footer && <footer className="px-6 py-3 border-t border-hairline">{footer}</footer>}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
