import * as Dialog from '@radix-ui/react-dialog'
import { cn } from '../../lib/cn'
import { Icon } from './Icon'

interface ModalProps {
  open: boolean
  onClose: () => void
  title: string
  description?: string
  children: React.ReactNode
  className?: string
  /** Extra classes for the title row (e.g. its own padding when `className` drops the panel's). */
  headerClassName?: string
  /** A click outside closes the dialog (default). Turn it off for a form whose input a stray
   *  click must not throw away: Esc and the close button still close it. */
  closeOnOutsideClick?: boolean
}

export function Modal({
  open, onClose, title, description, children, className, headerClassName, closeOnOutsideClick = true,
}: ModalProps) {
  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-inverse/40 animate-in fade-in-0" />
        <Dialog.Content
          onInteractOutside={closeOnOutsideClick ? undefined : (e) => e.preventDefault()}
          className={cn(
            'fixed z-50 left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2',
            'w-full max-w-md bg-surface-container-lowest rounded-2xl p-6',
            'shadow-[0_8px_40px_rgba(4,22,39,.18)]',
            'animate-in fade-in-0 zoom-in-95',
            'focus:outline-none',
            className,
          )}
        >
          <div className={cn('flex items-center justify-between mb-6', headerClassName)}>
            <div>
              <Dialog.Title className="text-base font-semibold text-on-surface">{title}</Dialog.Title>
              {description && (
                <Dialog.Description className="text-xs text-on-surface-variant mt-0.5">{description}</Dialog.Description>
              )}
            </div>
            <Dialog.Close asChild>
              <button
                aria-label="Close"
                className="p-1 rounded-lg text-on-surface-variant hover:bg-surface-container hover:text-on-surface transition-colors"
              >
                <Icon name="close" size={20} />
              </button>
            </Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
