import { useState, useRef, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { useProject, useTeam } from '../hooks/useProjects'
import {
  usePendingMembers, useInviteMember, useUpdateMemberRole, useRemoveMember, useCancelInvite,
} from '../hooks/useTeamMutations'
import { Card, Icon, Skeleton, Text } from '../components/ui'
import { cn } from '../lib/cn'
import type { TeamMember, UserRole } from '../types'

/* ─── Role badge (read-only) ─── */
function RolePill({ role }: { role: UserRole }) {
  const admin = role === 'admin'
  return (
    <span
      className={cn(
        'uppercase font-mono text-micro font-bold rounded-full tracking-[0.04em] whitespace-nowrap px-2 py-px',
        admin ? 'bg-surface-container text-secondary' : 'bg-[#f3f4f6] text-on-surface-variant',
      )}
    >
      {admin ? 'Admin' : 'Dev'}
    </span>
  )
}

/* ─── Role dropdown (admin can change) ─── */
function RoleSelect({ value, onChange }: { value: UserRole; onChange: (r: UserRole) => void }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    function onDown(e: MouseEvent) { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [])
  const label = value === 'admin' ? 'Admin' : 'Developer'
  return (
    <div className="relative inline-block" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 transition-colors hover:border-secondary hover:text-secondary px-2 py-[3px] border border-outline-variant rounded-md font-mono text-label font-semibold text-on-surface-variant bg-white"
      >
        <span>{label}</span>
        <Icon name="expand_more" size={11} />
      </button>
      {open && (
        <div className="absolute left-0 bg-white border border-outline-variant rounded-lg overflow-hidden top-[calc(100%+4px)] z-[200] shadow-[0_4px_20px_rgba(4,22,39,.12)] min-w-[150px]">
          {(['admin', 'developer'] as UserRole[]).map((r) => (
            <button
              key={r}
              onClick={() => { onChange(r); setOpen(false) }}
              className="w-full flex items-center justify-between px-3 py-2 hover:bg-surface-container-low text-on-surface font-mono text-caption"
            >
              <span>{r === 'admin' ? 'Admin' : 'Developer'}</span>
              {value === r && <Icon name="check" size={14} className="text-secondary" />}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

const ACCESS = [
  { role: 'admin' as UserRole, perms: 'Run analysis · Export DOCX · Manage team · Approve documents · Configure project settings' },
  { role: 'developer' as UserRole, perms: 'View documents · Download DOCX · Leave comments · Submit for review · Assign self to documents' },
]

export function TeamPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const pid = projectId ?? ''
  const { data: project } = useProject(pid)
  const { data: team, isLoading } = useTeam(pid)
  // Role is per-project (API my_role → project.userRole).
  const isAdmin = project?.userRole === 'admin'
  // The members endpoint returns active members only; pending invites come from
  // a separate admin-only endpoint, so merge them for the table.
  const { data: pending } = usePendingMembers(pid, isAdmin)

  const inviteMember = useInviteMember(pid)
  const updateRole = useUpdateMemberRole(pid)
  const removeMember = useRemoveMember(pid)
  const cancelInvite = useCancelInvite(pid)

  const [inviteOpen, setInviteOpen] = useState(false)
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<UserRole>('developer')

  const active = team ?? []
  const members: TeamMember[] = [...active, ...(pending ?? [])]
  const pendingCount = pending?.length ?? 0
  const roleOf = (m: TeamMember) => m.role

  return (
    <div className="flex-1 overflow-y-auto bg-surface-container-low">
      <div className="p-6 max-w-[860px] mx-auto">

        {/* ── Members card ── */}
        <Card className="overflow-hidden mb-5">
          <div className="px-5 py-4 border-b border-outline-variant flex items-center justify-between">
            <div>
              <Text as="h2" variant="heading" className="text-on-surface">Team</Text>
              <Text as="p" variant="caption" className="font-mono mt-0.5">
                {active.length} member{active.length !== 1 ? 's' : ''}{pendingCount > 0 ? ` · ${pendingCount} pending` : ''} · {project?.name ?? '…'}
              </Text>
            </div>
            {isAdmin && (
              <button
                onClick={() => setInviteOpen(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-secondary hover:bg-secondary-container text-white rounded-lg transition-colors font-mono text-caption font-medium tracking-[0.02em]"
              >
                <Icon name="person_add" size={15} />
                Invite
              </button>
            )}
          </div>

          <div className="overflow-x-auto">
            {isLoading ? (
              <div className="p-4 space-y-3">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-10" />)}</div>
            ) : (
              <table className="w-full">
                <thead>
                  <tr className="bg-surface-container-low border-b border-outline-variant">
                    <th className="text-left px-5 py-3 text-on-surface-variant uppercase font-mono text-caption font-medium tracking-[0.07em]">Member</th>
                    <th className="text-left px-4 py-3 text-on-surface-variant uppercase font-mono text-caption font-medium tracking-[0.07em] w-[120px]">Role</th>
                    <th className="text-left px-4 py-3 text-on-surface-variant uppercase font-mono text-caption font-medium tracking-[0.07em] w-[130px]">Last Active</th>
                    <th className="px-4 py-3 w-[120px]" />
                  </tr>
                </thead>
                <tbody>
                  {members.map((m) => (
                    <tr
                      key={m.id}
                      className={cn(
                        'border-b border-outline-variant last:border-0 transition-colors hover:bg-[#f8f9ff]',
                        m.pending && 'bg-[#fafafa]',
                      )}
                    >
                      {/* Member */}
                      <td className="px-5 py-3">
                        <div className="flex items-center gap-3">
                          {m.pending ? (
                            <div className="flex items-center justify-center flex-shrink-0 w-[34px] h-[34px] rounded-full border-2 border-dashed border-outline-variant">
                              <Icon name="person" size={16} className="text-on-surface-variant" />
                            </div>
                          ) : (
                            <div
                              className="flex items-center justify-center flex-shrink-0 w-[34px] h-[34px] rounded-full"
                              // eslint-disable-next-line no-restricted-syntax -- avatar colour is data-driven
                              style={{ background: m.avatarColor }}
                            >
                              {/* eslint-disable-next-line no-restricted-syntax -- avatar text colour is data-driven */}
                              <span className="font-sans text-caption font-bold" style={{ color: m.avatarTextColor }}>{m.initials}</span>
                            </div>
                          )}
                          <div className="min-w-0">
                            <p className={cn('truncate font-mono text-body font-medium', m.pending ? 'text-outline' : 'text-on-surface')}>{m.name}</p>
                            {m.pending && <p className="font-mono text-label text-amber">Pending</p>}
                          </div>
                        </div>
                      </td>
                      {/* Role */}
                      <td className="px-4 py-3">
                        {isAdmin && !m.pending
                          ? <RoleSelect value={roleOf(m)} onChange={(r) => m.userId && updateRole.mutate({ userId: m.userId, role: r })} />
                          : <RolePill role={roleOf(m)} />}
                      </td>
                      {/* Last active */}
                      <td className="px-4 py-3">
                        <Text variant="caption" className="font-mono">{m.lastActive}</Text>
                      </td>
                      {/* Actions */}
                      <td className="px-4 py-3">
                        {isAdmin && (
                          <div className="flex items-center gap-1.5">
                            {m.pending && (
                              <button
                                onClick={() => inviteMember.mutate({ email: m.email, role: m.role })}
                                className="inline-flex items-center gap-1 transition-colors hover:border-secondary hover:text-secondary px-2 py-[3px] border border-outline-variant rounded-md font-mono text-label font-semibold text-on-surface-variant bg-white"
                              >
                                <Icon name="send" size={12} />Resend
                              </button>
                            )}
                            <button
                              onClick={() => {
                                if (m.pending) {
                                  if (window.confirm(`Cancel invite for ${m.email || m.name}?`)) cancelInvite.mutate(m.id)
                                } else if (m.userId && window.confirm(`Remove ${m.name} from this project?`)) {
                                  removeMember.mutate(m.userId)
                                }
                              }}
                              className="p-1.5 rounded-lg hover:bg-surface-container transition-colors text-on-surface-variant"
                              aria-label={m.pending ? `Cancel invite for ${m.name}` : `Remove ${m.name}`}
                              title={m.pending ? 'Cancel invite' : 'Remove member'}
                            >
                              <Icon name={m.pending ? 'close' : 'person_remove'} size={16} />
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </Card>

        {/* ── Access reference card ── */}
        <Card className="overflow-hidden">
          <div className="px-5 py-3.5 border-b border-outline-variant">
            <Text as="h2" variant="heading" className="text-on-surface">Access</Text>
          </div>
          <div>
            {ACCESS.map((a, i) => (
              <div key={a.role} className={cn('flex items-start gap-3 px-5 py-3', i < ACCESS.length - 1 && 'border-b border-[#f3f4f6]')}>
                <span className="flex-shrink-0 mt-px"><RolePill role={a.role} /></span>
                <Text as="p" variant="caption" className="font-mono leading-relaxed">{a.perms}</Text>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* ── Invite modal ── */}
      {inviteOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-6 bg-[rgba(4,22,39,.45)]" onClick={() => setInviteOpen(false)}>
          <div className="bg-white rounded-xl border border-outline-variant w-full max-w-[440px] shadow-[0_8px_48px_rgba(4,22,39,.24)]" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-5 border-b border-outline-variant flex items-center justify-between">
              <div>
                <Text as="h3" variant="heading" className="text-on-surface">Invite to project</Text>
                <Text as="p" variant="caption" className="font-mono mt-0.5">{project?.name ?? '…'}</Text>
              </div>
              <button onClick={() => setInviteOpen(false)} className="p-1.5 hover:bg-surface-container rounded-lg transition-colors text-on-surface-variant">
                <Icon name="close" size={18} />
              </button>
            </div>
            <div className="px-6 py-5 space-y-4">
              <div>
                <label className="block text-on-surface-variant uppercase mb-1.5 font-mono text-caption font-semibold tracking-[0.06em]">Email</label>
                <input
                  type="email"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="colleague@company.com"
                  className="w-full h-11 px-3 border border-outline-variant rounded-xl bg-white focus:outline-none focus:border-secondary text-sm"
                />
              </div>
              <div className="space-y-2">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="radio" name="invite-role" checked={inviteRole === 'developer'} onChange={() => setInviteRole('developer')} className="accent-secondary" />
                  <span className="text-on-surface text-body">Developer</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="radio" name="invite-role" checked={inviteRole === 'admin'} onChange={() => setInviteRole('admin')} className="accent-secondary" />
                  <span className="text-on-surface text-body">Admin</span>
                </label>
              </div>
            </div>
            <div className="px-6 py-4 border-t border-outline-variant flex items-center justify-end gap-2">
              <button onClick={() => setInviteOpen(false)} className="px-4 py-2 border border-outline-variant hover:bg-surface-container rounded-lg text-on-surface-variant transition-colors font-mono text-xs">Cancel</button>
              <button
                disabled={!inviteEmail.trim() || inviteMember.isPending}
                onClick={() => {
                  const email = inviteEmail.trim()
                  if (!email) return
                  inviteMember.mutate({ email, role: inviteRole })
                  setInviteOpen(false)
                  setInviteEmail('')
                  setInviteRole('developer')
                }}
                className="flex items-center gap-1.5 px-4 py-2 bg-secondary hover:bg-secondary-container text-white rounded-lg transition-colors disabled:opacity-60 font-mono text-xs"
              >
                <Icon name="send" size={15} />Send Invite
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
