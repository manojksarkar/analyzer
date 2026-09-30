import { useState } from 'react'
import { Icon, Text } from '../../../components/ui'
import { cn } from '../../../lib/cn'
import type { TeamMember } from '../../../types'

/* ── Assign reviewers slide-in panel ── */
export function AssignReviewersPanel({
  members, refLabel, shortSha, busy, onClose, onAssign,
}: {
  members: TeamMember[]
  refLabel: string
  shortSha?: string
  busy: boolean
  onClose: () => void
  onAssign: (userId: string) => void
}) {
  const [selected, setSelected] = useState<string | null>(null)
  const selectedMember = members.find((m) => (m.userId ?? m.id) === selected)

  return (
    <div className="absolute right-0 top-0 bottom-0 w-[320px] bg-white border-l border-outline-variant flex flex-col z-30 shadow-[-4px_0_20px_rgba(4,22,39,.08)]">
      <div className="flex-shrink-0 px-4 py-3 border-b border-outline-variant flex items-center justify-between">
        <div>
          <Text as="p" variant="mono" className="text-on-surface">Assign Reviewers</Text>
          <Text as="p" variant="caption" className="font-mono mt-0.5">{refLabel}{shortSha ? ` · ${shortSha}` : ''}</Text>
        </div>
        <button onClick={onClose} className="p-1 hover:bg-surface-container rounded-lg transition-colors">
          <Icon name="close" size={18} className="text-on-surface-variant" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4">
        <Text variant="label" className="block text-on-surface-variant tracking-[0.08em] mb-2">Select reviewer</Text>
        <div className="space-y-1">
          {members.length === 0 && (
            <Text as="p" variant="caption" className="font-mono">No team members to assign.</Text>
          )}
          {members.map((m) => {
            const uid = m.userId ?? m.id
            const active = selected === uid
            return (
              <button
                key={m.id}
                onClick={() => setSelected(uid)}
                className={cn(
                  'w-full flex items-center gap-2.5 px-3 py-2 rounded-lg border transition-colors text-left',
                  active ? 'border-secondary bg-surface-container-low' : 'border-outline-variant hover:border-secondary hover:bg-surface-container-low',
                )}
              >
                <div
                  className="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0"
                  // eslint-disable-next-line no-restricted-syntax -- member avatar colour is data-driven
                  style={{ background: m.avatarColor }}
                >
                  {/* eslint-disable-next-line no-restricted-syntax -- member avatar text colour is data-driven */}
                  <span className="font-bold font-sans text-micro" style={{ color: m.avatarTextColor }}>{m.initials}</span>
                </div>
                <span className="flex-1 font-mono text-caption text-on-surface truncate">{m.name}</span>
                {active && <Icon name="check" size={16} className="text-secondary flex-shrink-0" />}
              </button>
            )
          })}
        </div>
        <Text as="p" variant="caption" className="font-mono mt-3">
          {selectedMember ? `Selected: ${selectedMember.name}` : 'No reviewer selected'}
        </Text>
      </div>

      <div className="flex-shrink-0 px-4 py-3 border-t border-outline-variant">
        <button
          disabled={!selected || busy}
          onClick={() => selected && onAssign(selected)}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-secondary text-white hover:bg-secondary-container rounded-xl transition-colors font-mono text-caption font-medium disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Icon name="send" size={16} />
          Send for Review
        </button>
      </div>
    </div>
  )
}
