import { Link } from 'react-router-dom'
import { Avatar, StatusBadge } from '../../../components/ui'
import type { Document } from '../../../types'

/* ─── The open document's review state: shown, never changed, here ─── */
// Compare is for reading changes. A document is reviewed and approved in the document itself
// (compare.html renderDocStateBar).
export function DocStateBar({ doc, projectId }: { doc: Document; projectId: string }) {
  const carried = doc.review.carriedFrom
  return (
    <div className="flex-shrink-0 h-9 border-t border-outline-variant bg-surface-container-lowest px-4 flex items-center justify-between gap-3">
      <div className="flex items-center gap-2 min-w-0">
        <StatusBadge status={doc.status} suffix={carried ? ` · from ${carried.tag}` : undefined} />
        {doc.status !== 'approved' && (doc.reviewer ? (
          <span className="flex items-center gap-1.5 font-mono text-label text-outline whitespace-nowrap">
            <Avatar person={doc.reviewer} size={16} />Reviewer: {doc.reviewer.name}
          </span>
        ) : (
          <span className="font-mono text-label text-warn whitespace-nowrap">Needs a reviewer</span>
        ))}
      </div>
      <Link
        to={`/projects/${projectId}/documents/${doc.id}?tab=review`}
        className="font-mono text-caption font-medium text-secondary hover:underline whitespace-nowrap"
      >
        Review and approve in the document →
      </Link>
    </div>
  )
}
