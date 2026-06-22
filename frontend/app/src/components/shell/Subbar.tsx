import type { ReactNode } from 'react'
import type { Version, Commit } from '../../types'

interface CommitChipProps {
  version?: Version
  commit?: Commit
}

function CommitChip({ version, commit }: CommitChipProps) {
  const style: React.CSSProperties = {
    fontFamily: "'JetBrains Mono'",
    fontSize: 11,
    fontWeight: 500,
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
    padding: '5px 10px',
    border: '1px solid #c4c6cd',
    borderRadius: 6,
    background: '#fff',
    cursor: 'pointer',
    transition: 'background .1s, border-color .1s',
    whiteSpace: 'nowrap',
  }

  if (version) {
    return (
      <span style={style}>
        <span className="material-symbols-outlined sym-fill text-on-tertiary-container" style={{ fontSize: 13 }} aria-hidden>sell</span>
        <span className="text-on-surface font-semibold">{version.branch} @ {version.shortSha}</span>
        <span className="material-symbols-outlined text-on-surface-variant" style={{ fontSize: 13 }} aria-hidden>expand_more</span>
      </span>
    )
  }
  if (commit) {
    return (
      <span style={style}>
        <span className="material-symbols-outlined text-on-tertiary-container" style={{ fontSize: 13 }} aria-hidden>alt_route</span>
        <span className="text-on-surface font-semibold">{commit.branch} @ {commit.shortSha}</span>
        <span className="material-symbols-outlined text-on-surface-variant" style={{ fontSize: 13 }} aria-hidden>expand_more</span>
      </span>
    )
  }
  return null
}

interface SubbarProps {
  projectName: string
  selectedVersion?: Version
  selectedCommit?: Commit
  statusBadge?: ReactNode
  cta?: ReactNode
}

export function Subbar({ projectName, selectedVersion, selectedCommit, statusBadge, cta }: SubbarProps) {
  return (
    <div className="h-12 flex-shrink-0 flex items-center justify-between px-4 bg-white border-b border-outline-variant z-20">
      <div className="flex items-center gap-2">
        {/* Project switcher pill */}
        <button
          className="inline-flex items-center gap-1.5 px-2.5 py-[5px] border border-outline-variant rounded-md bg-white transition-colors hover:bg-surface-container-low hover:border-secondary"
          style={{ fontFamily: "'JetBrains Mono'", fontSize: 12 }}
        >
          <span className="material-symbols-outlined sym-fill text-secondary" style={{ fontSize: 14 }} aria-hidden>folder</span>
          <span className="text-on-surface font-medium">{projectName}</span>
          <span className="material-symbols-outlined text-on-surface-variant" style={{ fontSize: 13 }} aria-hidden>expand_more</span>
        </button>

        {(selectedVersion ?? selectedCommit) && (
          <>
            <span className="text-outline-variant select-none" aria-hidden>·</span>
            <CommitChip version={selectedVersion} commit={selectedCommit} />
          </>
        )}

        {statusBadge && (
          <>
            <span className="text-outline-variant select-none" aria-hidden>·</span>
            {statusBadge}
          </>
        )}
      </div>

      {cta && <div className="flex items-center gap-1.5">{cta}</div>}
    </div>
  )
}
