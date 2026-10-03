import { Component, type ReactNode, type ErrorInfo } from 'react'
import { Button } from './ui'

interface Props {
  children: ReactNode
  fallback?: ReactNode
  /** When it changes, a caught error is cleared — the page's location, so moving away from a
   *  crashed page shows the next one. A `key` would do it too, but would also remount every
   *  healthy page on each navigation (a document switch lost the reader's state). */
  resetKey?: unknown
}

interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary]', error, info)
  }

  componentDidUpdate(prev: Props) {
    if (this.state.hasError && !Object.is(prev.resetKey, this.props.resetKey)) this.reset()
  }

  reset = () => this.setState({ hasError: false, error: null })

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback
      return (
        <div className="flex flex-col items-center justify-center p-12 text-center gap-4">
          <div className="w-14 h-14 rounded-full bg-error/10 flex items-center justify-center">
            <span className="material-symbols-outlined text-error" style={{ fontSize: 28 }} aria-hidden>
              error_outline
            </span>
          </div>
          <div>
            <h2 className="text-base font-semibold text-on-surface mb-1">Something went wrong</h2>
            <p className="text-xs text-on-surface-variant max-w-xs">
              {this.state.error?.message ?? 'An unexpected error occurred.'}
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={this.reset}>
            <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden>refresh</span>
            Try again
          </Button>
        </div>
      )
    }
    return this.props.children
  }
}
