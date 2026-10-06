import * as ToastPrimitive from '@radix-ui/react-toast'
import { create } from 'zustand'
import { cn } from '../../lib/cn'
import { CodeText } from './CodeText'

type ToastVariant = 'default' | 'success' | 'error'

/** One plain verb the toast offers (Done editing's "Update"). */
export interface ToastAction {
  label: string
  onClick: () => void
}

interface ToastItem {
  id: string
  title: string
  description?: string
  variant?: ToastVariant
  action?: ToastAction
}

interface ToastStore {
  toasts: ToastItem[]
  push: (t: Omit<ToastItem, 'id'>) => void
  dismiss: (id: string) => void
}

/* A toast's id only has to be unique on this page. `crypto.randomUUID` exists only in a secure
   context (https or localhost): over plain http it is undefined, and every toast threw — which
   broke the save and approve handlers that raise one. A counter needs nothing. */
let toastSeq = 0
const nextToastId = (): string => `toast-${++toastSeq}`

export const useToastStore = create<ToastStore>((set) => ({
  toasts: [],
  push: (t) =>
    set((s) => ({
      toasts: [...s.toasts, { ...t, id: nextToastId() }],
    })),
  dismiss: (id) =>
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))

export const toast = {
  success: (title: string, description?: string) =>
    useToastStore.getState().push({ title, description, variant: 'success' }),
  error: (title: string, description?: string) =>
    useToastStore.getState().push({ title, description, variant: 'error' }),
  info: (title: string, description?: string, action?: ToastAction) =>
    useToastStore.getState().push({ title, description, variant: 'default', action }),
}

const iconMap: Record<ToastVariant, { name: string; color: string }> = {
  default: { name: 'info', color: '#0058be' },
  success: { name: 'check_circle', color: '#00a572' },
  error:   { name: 'error', color: '#ba1a1a' },
}

export function ToastProvider() {
  const { toasts, dismiss } = useToastStore()

  return (
    <ToastPrimitive.Provider swipeDirection="right">
      {toasts.map((t) => {
        const icon = iconMap[t.variant ?? 'default']
        return (
          <ToastPrimitive.Root
            key={t.id}
            open
            onOpenChange={(open) => !open && dismiss(t.id)}
            duration={t.action ? 8000 : 4000}
            className={cn(
              'flex items-start gap-3 p-4 rounded-xl border border-outline-variant bg-white',
              'shadow-[0_4px_24px_rgba(4,22,39,.12)]',
              'data-[state=open]:animate-in data-[state=open]:slide-in-from-right-full',
              'data-[state=closed]:animate-out data-[state=closed]:fade-out-80',
            )}
          >
            <span className="material-symbols-outlined sym-fill mt-0.5 flex-shrink-0" style={{ fontSize: 18, color: icon.color }} aria-hidden>
              {icon.name}
            </span>
            <div className="flex-1 min-w-0">
              <ToastPrimitive.Title className="text-sm font-semibold text-on-surface">{t.title}</ToastPrimitive.Title>
              {t.description && (
                <ToastPrimitive.Description className="text-xs text-on-surface-variant mt-0.5 break-words"><CodeText text={t.description} /></ToastPrimitive.Description>
              )}
              {t.action && (
                <ToastPrimitive.Action
                  altText={t.action.label}
                  onClick={t.action.onClick}
                  className="mt-1 text-xs font-semibold text-secondary hover:underline"
                >
                  {t.action.label}
                </ToastPrimitive.Action>
              )}
            </div>
            <ToastPrimitive.Close aria-label="Dismiss" className="text-on-surface-variant hover:text-on-surface transition-colors flex-shrink-0">
              <span className="material-symbols-outlined" style={{ fontSize: 16 }} aria-hidden>close</span>
            </ToastPrimitive.Close>
          </ToastPrimitive.Root>
        )
      })}
      <ToastPrimitive.Viewport className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2 w-80 outline-none" />
    </ToastPrimitive.Provider>
  )
}
