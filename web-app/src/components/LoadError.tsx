import { Button, Icon, Text } from './ui'
import { cn } from '../lib/cn'

/** The message a failed read carries (the http client puts the API's own on `Error.message`). */
function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message
  return typeof error === 'string' && error ? error : 'The server did not answer.'
}

/**
 * A read that failed: what failed, the server's message, and Retry. A failed load must never
 * look like an empty page ("No documents", "Not found"): those are answers, this is not one.
 * `compact` is a line inside a panel; otherwise a centred block that fills its area.
 */
export function LoadError({ what, error, onRetry, retrying, compact, className }: {
  /** What could not be read, as in "Could not load {what}". */
  what: string
  error: unknown
  onRetry: () => void
  /** A retry is under way. */
  retrying?: boolean
  compact?: boolean
  className?: string
}) {
  const retry = (
    <Button variant="outline" size="sm" loading={retrying} onClick={onRetry}>
      {!retrying && <Icon name="refresh" size={14} />}Retry
    </Button>
  )
  if (compact) {
    return (
      <div role="alert" className={cn('flex items-center gap-3 rounded-lg border border-error/30 bg-error-container/40 px-4 py-3', className)}>
        <Icon name="error" size={18} className="text-error flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <Text as="p" variant="body" className="text-on-surface font-medium">Could not load {what}</Text>
          <Text as="p" variant="caption" className="font-mono break-words">{errorMessage(error)}</Text>
        </div>
        {retry}
      </div>
    )
  }
  return (
    <div role="alert" className={cn('flex flex-col items-center justify-center text-center gap-4 px-6 py-16', className)}>
      <div className="w-14 h-14 rounded-full bg-error/10 flex items-center justify-center">
        <Icon name="error_outline" size={28} className="text-error" />
      </div>
      <div className="max-w-[420px]">
        <Text as="p" variant="heading" className="text-on-surface">Could not load {what}</Text>
        <Text as="p" variant="caption" className="font-mono mt-1 break-words">{errorMessage(error)}</Text>
      </div>
      {retry}
    </div>
  )
}
