import { useState, useRef, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { useProject, useTeam } from '../hooks/useProjects'
import { useUIStore } from '../store/ui'
import { Skeleton } from '../components/ui'
import type { TeamMember, UserRole } from '../types'

/* ─── Role badge (read-only) ─── */
function RolePill({ role }: { role: UserRole }) {
  const admin = role === 'admin'
  return (
    <span
      className="uppercase"
      style={{
        fontFamily: "'JetBrains Mono'", fontSize: 9, fontWeight: 700,
        background: admin ? '#e5eeff' : '#f3f4f6', color: admin ? '#0058be' : '#44474c',
        padding: '1px 8px', borderRadius: 99, letterSpacing: '0.04em', whiteSpace: 'nowrap',
      }}
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
        className="inline-flex items-center gap-1 transition-colors hover:border-secondary hover:text-secondary"
        style={{ padding: '3px 8px', border: '1px solid #c4c6cd', borderRadius: 6, fontFamily: "'JetBrains Mono'", fontSize: 10, fontWeight: 600, color: '#44474c', background: '#fff' }}
      >
        <span>{label}</span>
        <span className="material-symbols-outlined" style={{ fontSize: 11 }} aria-hidden>expand_more</span>
      </button>
      {open && (
        <div
          className="absolute left-0 bg-white border border-outline-variant rounded-lg overflow-hidden"
          style={{ top: 'calc(100% + 4px)', zIndex: 200, boxShadow: '0 4px 20px rgba(4,22,39,.12)', minWidth: 150 }}
        >
          {(['admin', 'developer'] as UserRole[]).map((r) => (
            <button
              key={r}
              onClick={() => { onChange(r); setOpen(false) }}
              className="w-full flex items-center justify-between px-3 py-2 hover:bg-surface-container-low text-on-surface"
              style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}
            >
              <span>{r === 'admin' ? 'Admin' : 'Developer'}</span>
              {value === r && <span className="material-symbols-outlined text-secondary" style={{ fontSize: 14 }} aria-hidden>check</span>}
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
  const { data: project } = useProject(projectId ?? '')
  const { data: team, isLoading } = useTeam(projectId ?? '')
  const roleView = useUIStore((s) => s.roleView)
  const isAdmin = roleView === 'admin'

  const [roles, setRoles] = useState<Record<string, UserRole>>({})
  const [inviteOpen, setInviteOpen] = useState(false)

  const members = team ?? []
  const active = members.filter((m) => !m.pending)
  const pendingCount = members.filter((m) => m.pending).length
  const roleOf = (m: TeamMember) => roles[m.id] ?? m.role

  return (
    <div className="flex-1 overflow-y-auto" style={{ background: '#eff4ff' }}>
      <div className="p-6" style={{ maxWidth: 860, margin: '0 auto' }}>

        {/* ── Members card ── */}
        <div className="bg-white border border-outline-variant rounded-xl overflow-hidden mb-5">
          <div className="px-5 py-4 border-b border-outline-variant flex items-center justify-between">
            <div>
              <h2 className="text-on-surface font-semibold" style={{ fontSize: 18 }}>Team</h2>
              <p className="text-on-surface-variant mt-0.5" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>
                {active.length} member{active.length !== 1 ? 's' : ''}{pendingCount > 0 ? ` · ${pendingCount} pending` : ''} · {project?.name ?? '…'}
              </p>
            </div>
            {isAdmin && (
              <button
                onClick={() => setInviteOpen(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-secondary hover:bg-secondary-container text-white rounded-lg transition-colors"
                style={{ fontFamily: "'JetBrains Mono'", fontSize: 11, fontWeight: 500, letterSpacing: '0.02em' }}
              >
                <span className="material-symbols-outlined" style={{ fontSize: 15 }} aria-hidden>person_add</span>
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
                    <th className="text-left px-5 py-3 text-on-surface-variant uppercase" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11, fontWeight: 500, letterSpacing: '0.07em' }}>Member</th>
                    <th className="text-left px-4 py-3 text-on-surface-variant uppercase" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11, fontWeight: 500, letterSpacing: '0.07em', width: 120 }}>Role</th>
                    <th className="text-left px-4 py-3 text-on-surface-variant uppercase" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11, fontWeight: 500, letterSpacing: '0.07em', width: 130 }}>Last Active</th>
                    <th className="px-4 py-3" style={{ width: 120 }} />
                  </tr>
                </thead>
                <tbody>
                  {members.map((m) => (
                    <tr
                      key={m.id}
                      className="border-b border-outline-variant last:border-0 transition-colors hover:bg-[#f8f9ff]"
                      style={{ background: m.pending ? '#fafafa' : undefined }}
                    >
                      {/* Member */}
                      <td className="px-5 py-3">
                        <div className="flex items-center gap-3">
                          {m.pending ? (
                            <div className="flex items-center justify-center flex-shrink-0" style={{ width: 34, height: 34, borderRadius: '50%', border: '2px dashed #c4c6cd' }}>
                              <span className="material-symbols-outlined text-on-surface-variant" style={{ fontSize: 16 }} aria-hidden>person</span>
                            </div>
                          ) : (
                            <div className="flex items-center justify-center flex-shrink-0" style={{ width: 34, height: 34, borderRadius: '50%', background: m.avatarColor }}>
                              <span style={{ fontFamily: 'Inter', fontSize: 11, fontWeight: 700, color: m.avatarTextColor }}>{m.initials}</span>
                            </div>
                          )}
                          <div className="min-w-0">
                            <p className="truncate" style={{ fontFamily: "'JetBrains Mono'", fontSize: 13, fontWeight: 500, color: m.pending ? '#74777d' : '#0b1c30' }}>{m.name}</p>
                            {m.pending && <p style={{ fontFamily: "'JetBrains Mono'", fontSize: 10, color: '#f59e0b' }}>Pending</p>}
                          </div>
                        </div>
                      </td>
                      {/* Role */}
                      <td className="px-4 py-3">
                        {isAdmin && !m.pending
                          ? <RoleSelect value={roleOf(m)} onChange={(r) => setRoles((prev) => ({ ...prev, [m.id]: r }))} />
                          : <RolePill role={roleOf(m)} />}
                      </td>
                      {/* Last active */}
                      <td className="px-4 py-3">
                        <span className="text-on-surface-variant" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>{m.lastActive}</span>
                      </td>
                      {/* Actions */}
                      <td className="px-4 py-3">
                        {isAdmin && (
                          <div className="flex items-center gap-1.5">
                            {m.pending && (
                              <button
                                className="inline-flex items-center gap-1 transition-colors hover:border-secondary hover:text-secondary"
                                style={{ padding: '3px 8px', border: '1px solid #c4c6cd', borderRadius: 6, fontFamily: "'JetBrains Mono'", fontSize: 10, fontWeight: 600, color: '#44474c', background: '#fff' }}
                              >
                                <span className="material-symbols-outlined" style={{ fontSize: 12 }} aria-hidden>send</span>Resend
                              </button>
                            )}
                            <button
                              className="p-1.5 rounded-lg hover:bg-surface-container transition-colors text-on-surface-variant"
                              aria-label={`Actions for ${m.name}`}
                            >
                              <span className="material-symbols-outlined" style={{ fontSize: 16 }} aria-hidden>more_vert</span>
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
        </div>

        {/* ── Access reference card ── */}
        <div className="bg-white border border-outline-variant rounded-xl overflow-hidden">
          <div className="px-5 py-3.5 border-b border-outline-variant">
            <h2 className="text-on-surface font-semibold" style={{ fontSize: 18 }}>Access</h2>
          </div>
          <div>
            {ACCESS.map((a, i) => (
              <div key={a.role} className="flex items-start gap-3" style={{ padding: '12px 20px', borderBottom: i < ACCESS.length - 1 ? '1px solid #f3f4f6' : 'none' }}>
                <span className="flex-shrink-0" style={{ marginTop: 1 }}><RolePill role={a.role} /></span>
                <p className="text-on-surface-variant leading-relaxed" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>{a.perms}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── Invite modal ── */}
      {inviteOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-6" style={{ background: 'rgba(4,22,39,.45)' }} onClick={() => setInviteOpen(false)}>
          <div className="bg-white rounded-xl border border-outline-variant w-full" style={{ maxWidth: 440, boxShadow: '0 8px 48px rgba(4,22,39,.24)' }} onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-5 border-b border-outline-variant flex items-center justify-between">
              <div>
                <h3 className="text-on-surface font-semibold" style={{ fontSize: 18 }}>Invite to project</h3>
                <p className="text-on-surface-variant mt-0.5" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>{project?.name ?? '…'}</p>
              </div>
              <button onClick={() => setInviteOpen(false)} className="p-1.5 hover:bg-surface-container rounded-lg transition-colors text-on-surface-variant">
                <span className="material-symbols-outlined" style={{ fontSize: 18 }} aria-hidden>close</span>
              </button>
            </div>
            <div className="px-6 py-5 space-y-4">
              <div>
                <label className="block text-on-surface-variant uppercase mb-1.5" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11, fontWeight: 600, letterSpacing: '0.06em' }}>Email</label>
                <input type="email" placeholder="colleague@company.com" className="w-full h-11 px-3 border border-outline-variant rounded-xl bg-white focus:outline-none focus:border-secondary" style={{ fontSize: 14 }} />
              </div>
              <div className="space-y-2">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="radio" name="invite-role" defaultChecked className="accent-secondary" />
                  <span className="text-on-surface" style={{ fontSize: 13 }}>Developer</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="radio" name="invite-role" className="accent-secondary" />
                  <span className="text-on-surface" style={{ fontSize: 13 }}>Admin</span>
                </label>
              </div>
            </div>
            <div className="px-6 py-4 border-t border-outline-variant flex items-center justify-end gap-2">
              <button onClick={() => setInviteOpen(false)} className="px-4 py-2 border border-outline-variant hover:bg-surface-container rounded-lg text-on-surface-variant transition-colors" style={{ fontFamily: "'JetBrains Mono'", fontSize: 12 }}>Cancel</button>
              <button onClick={() => setInviteOpen(false)} className="flex items-center gap-1.5 px-4 py-2 bg-secondary hover:bg-secondary-container text-white rounded-lg transition-colors" style={{ fontFamily: "'JetBrains Mono'", fontSize: 12 }}>
                <span className="material-symbols-outlined" style={{ fontSize: 15 }} aria-hidden>send</span>Send Invite
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
