import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useProject, useTeam } from '../../hooks/useProjects'
import {
  usePendingMembers, useInviteMember, useUpdateMemberRole, useRemoveMember, useCancelInvite,
} from '../../hooks/useTeamMutations'
import { useAuthStore } from '../../store/auth'
import { Card, Icon, Skeleton, Text } from '../../components/ui'
import { SubbarCta } from '../../components/shell/SubbarCta'
import { cn } from '../../lib/cn'
import type { TeamMember, UserRole } from '../../types'
import { AddMemberDialog } from './components/AddMemberDialog'
import { ConfirmMemberChange } from './components/ConfirmMemberChange'
import { RolePill, RoleSelect } from './components/RoleControls'
import { LAST_ADMIN_REASON, asksBeforeRoleChange, isLastAdmin, type MemberChange } from './helpers'

// Two roles, no reviewer role: whoever is assigned to a document reviews it (REVIEW_APPROVE_DESIGN).
const ACCESS = [
  { role: 'admin' as UserRole, perms: 'Run analysis · Update and rebuild Word files · Manage team · Assign reviewers · Approve, request changes, reopen documents · Configure project settings' },
  { role: 'developer' as UserRole, perms: "View and download documents · Correct the LLM's text · Review the documents assigned to them · Update their Word files · Submit for approval · Claim an unassigned document" },
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

  const navigate = useNavigate()
  const meId = useAuthStore((s) => s.user?.id ?? '')

  const [inviteOpen, setInviteOpen] = useState(false)
  // Removing anyone, or taking your own admin role away, is asked first.
  const [confirm, setConfirm] = useState<MemberChange | null>(null)

  const active = team ?? []
  const members: TeamMember[] = [...active, ...(pending ?? [])]
  const pendingCount = pending?.length ?? 0
  const roleOf = (m: TeamMember) => m.role

  function changeRole(m: TeamMember, role: UserRole) {
    if (!m.userId || role === m.role) return
    if (asksBeforeRoleChange(m, role, meId)) setConfirm({ action: 'demote', member: m })
    else updateRole.mutate({ userId: m.userId, role })
  }
  function confirmChange() {
    const userId = confirm?.member.userId
    if (!confirm || !userId) return
    const done = { onSettled: () => setConfirm(null) }
    if (confirm.action === 'demote') {
      updateRole.mutate({ userId, role: 'developer' }, done)
    } else {
      // Removing yourself: the project is no longer yours to see.
      removeMember.mutate(userId, { ...done, onSuccess: () => { if (userId === meId) navigate('/projects') } })
    }
  }

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
          </div>
          {/* The page's Subbar action (mockup), as Documents' Download All and Overview's Run Analysis. */}
          {isAdmin && (
            <SubbarCta>
              <button
                onClick={() => setInviteOpen(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-secondary hover:bg-secondary-container text-on-secondary rounded-lg transition-colors font-mono text-caption font-bold tracking-[0.04em]"
              >
                <Icon name="person_add" size={14} />
                ADD MEMBER
              </button>
            </SubbarCta>
          )}

          {/* Room under the last row for its role menu, which opens downwards inside this box. */}
          <div className="overflow-x-auto pb-16">
            {isLoading ? (
              <div className="p-4 space-y-3">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-10" />)}</div>
            ) : (
              <table className="w-full">
                <thead>
                  <tr className="bg-surface-container-low border-b border-outline-variant">
                    <th className="text-left px-5 py-3 text-on-surface-variant uppercase font-mono text-caption font-medium tracking-[0.07em]">Member</th>
                    <th className="text-left px-4 py-3 text-on-surface-variant uppercase font-mono text-caption font-medium tracking-[0.07em] w-[120px]">Role</th>
                    <th className="text-left px-4 py-3 text-on-surface-variant uppercase font-mono text-caption font-medium tracking-[0.07em] w-[130px]">Last Active</th>
                    <th className="text-left px-4 py-3 text-on-surface-variant uppercase font-mono text-caption font-medium tracking-[0.07em] w-[120px]">{isAdmin ? 'Actions' : ''}</th>
                  </tr>
                </thead>
                <tbody>
                  {members.map((m) => {
                    // The only active admin is neither demoted nor removed (the API: 409 LAST_ADMIN).
                    const onlyAdmin = isLastAdmin(m, members) ? LAST_ADMIN_REASON : null
                    return (
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
                            ? <RoleSelect value={roleOf(m)} label={m.name} demoteLocked={onlyAdmin} onChange={(r) => changeRole(m, r)} />
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
                                  <Icon name="how_to_reg" size={12} />Activate
                                </button>
                              )}
                              <button
                                onClick={() => {
                                  if (m.pending) {
                                    if (window.confirm(`Cancel invite for ${m.email || m.name}?`)) cancelInvite.mutate(m.id)
                                  } else if (m.userId) {
                                    setConfirm({ action: 'remove', member: m })
                                  }
                                }}
                                disabled={!!onlyAdmin}
                                className="p-1.5 rounded-lg hover:bg-surface-container transition-colors text-on-surface-variant disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent"
                                aria-label={m.pending ? `Cancel invite for ${m.name}` : `Remove ${m.name}`}
                                title={m.pending ? 'Cancel invite' : onlyAdmin ?? 'Remove member'}
                              >
                                <Icon name={m.pending ? 'close' : 'person_remove'} size={16} />
                              </button>
                            </div>
                          )}
                        </td>
                      </tr>
                    )
                  })}
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
            {ACCESS.map((a) => (
              <div key={a.role} className="flex items-start gap-3 px-5 py-3 border-b border-[#f3f4f6]">
                <span className="flex flex-shrink-0 mt-px"><RolePill role={a.role} /></span>
                <Text as="p" variant="caption" className="font-mono leading-relaxed">{a.perms}</Text>
              </div>
            ))}
            <div className="flex items-start gap-3 px-5 py-3 bg-surface">
              <Icon name="info" size={15} className="text-on-surface-variant flex-shrink-0 mt-px" />
              <Text as="p" variant="caption" className="font-mono leading-relaxed">
                Reviewer is not a role: whoever is assigned to a document reviews it — one reviewer per document.
              </Text>
            </div>
          </div>
        </Card>
      </div>

      {inviteOpen && (
        <AddMemberDialog
          projectId={pid}
          projectName={project?.name}
          members={members}
          onClose={() => setInviteOpen(false)}
        />
      )}
      {confirm && (
        <ConfirmMemberChange
          change={confirm}
          isMe={!!meId && confirm.member.userId === meId}
          projectName={project?.name}
          busy={updateRole.isPending || removeMember.isPending}
          onConfirm={confirmChange}
          onClose={() => setConfirm(null)}
        />
      )}
    </div>
  )
}
