import * as Dialog from '@radix-ui/react-dialog'
import { cn } from '../../lib/cn'

interface ModalProps {
  open: boolean
  onClose: () => void
  title: string
  description?: string
  children: React.ReactNode
  className?: string
}

export function Modal({ open, onClose, title, description, children, className }: ModalProps) {
  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-primary/40 animate-in fade-in-0" />
        <Dialog.Content
          className={cn(
            'fixed z-50 left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2',
            'w-full max-w-md bg-white rounded-2xl p-6',
            'shadow-[0_8px_40px_rgba(4,22,39,.18)]',
            'animate-in fade-in-0 zoom-in-95',
            'focus:outline-none',
            className,
          )}
        >
          <div className="flex items-center justify-between mb-6">
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
                <span className="material-symbols-outlined" style={{ fontSize: 20 }} aria-hidden>close</span>
              </button>
            </Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
