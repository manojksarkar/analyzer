import { Component, type ReactNode, type ErrorInfo } from 'react'
import { Button } from './ui'

interface Props {
  children: ReactNode
  fallback?: ReactNode
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
