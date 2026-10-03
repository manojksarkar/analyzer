import { Link, useLocation } from 'react-router-dom'
import { Icon, Text } from '../components/ui'

/** An address no page answers. It used to send you to Projects without a word, so a mistyped or
 *  stale link looked like the app had lost your place. */
export function NotFoundPage() {
  const { pathname } = useLocation()
  return (
    <div className="h-screen flex flex-col items-center justify-center gap-4 text-center p-8 bg-background">
      <div className="w-14 h-14 rounded-full bg-surface-container-low border border-outline-variant flex items-center justify-center">
        <Icon name="explore_off" size={28} className="text-on-surface-variant" />
      </div>
      <div>
        <Text as="h1" variant="heading" className="text-on-surface mb-1">Page not found</Text>
        <Text as="p" variant="caption" className="font-mono break-all">Nothing is at {pathname}.</Text>
      </div>
      <Link
        to="/projects"
        className="inline-flex items-center gap-1.5 h-9 px-4 rounded-lg border border-outline-variant text-on-surface hover:bg-surface-container transition-colors text-sm font-semibold"
      >
        <Icon name="arrow_back" size={16} />
        Back to projects
      </Link>
    </div>
  )
}
