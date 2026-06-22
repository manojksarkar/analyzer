import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { useTeam } from '../hooks/useProjects'
import { Button, Input, Select, Modal, RoleBadge, TableSkeleton } from '../components/ui'
import { toast } from '../components/ui/Toast'
import { Dropdown, DropdownTrigger, DropdownContent } from '../components/ui'

const inviteSchema = z.object({
  email: z.string().email('Enter a valid email'),
  role: z.enum(['developer', 'admin']),
})
type InviteForm = z.infer<typeof inviteSchema>

const PERMISSION_MATRIX = [
  { permission: 'Create & delete projects', admin: true,  developer: false },
  { permission: 'Manage team members',      admin: true,  developer: false },
  { permission: 'Configure architecture',   admin: true,  developer: false },
  { permission: 'Run analysis',             admin: true,  developer: true  },
  { permission: 'Review & comment',         admin: true,  developer: true  },
  { permission: 'Approve documents',        admin: true,  developer: false },
  { permission: 'Export DOCX',              admin: true,  developer: true  },
]

export function TeamPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const [showInvite, setShowInvite] = useState(false)

  const { data: team, isLoading } = useTeam(projectId ?? '')

  const {
    register,
    handleSubmit,
    reset,
    setValue,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<InviteForm>({
    resolver: zodResolver(inviteSchema),
    defaultValues: { role: 'developer' },
  })

  async function onInvite(data: InviteForm) {
    await new Promise((r) => setTimeout(r, 600))
    toast.success('Invitation sent', `${data.email} has been invited as ${data.role}.`)
    reset()
    setShowInvite(false)
  }

  return (
    <div className="p-6">
      <Modal
        open={showInvite}
        onClose={() => setShowInvite(false)}
        title="Invite Member"
        description="They will receive an email invitation to join this project."
      >
        <form onSubmit={handleSubmit(onInvite)} noValidate className="space-y-4">
          <Input
            label="Work email"
            type="email"
            placeholder="colleague@company.com"
            leadingIcon="mail"
            error={errors.email?.message}
            {...register('email')}
          />
          <Select
            label="Role"
            value={watch('role')}
            onValueChange={(v) => setValue('role', v as 'developer' | 'admin')}
            options={[
              { value: 'developer', label: 'Developer' },
              { value: 'admin',     label: 'Admin' },
            ]}
          />
          <div className="flex items-center gap-3 pt-2">
            <Button type="button" variant="outline" className="flex-1" onClick={() => setShowInvite(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={isSubmitting} className="flex-1">
              Send Invite
            </Button>
          </div>
        </form>
      </Modal>

      <div className="grid gap-6 items-start" style={{ gridTemplateColumns: '1fr 300px' }}>
        {/* Member table */}
        <div className="bg-white border border-outline-variant rounded-xl overflow-hidden">
          <div className="flex items-center justify-between px-5 py-3.5 border-b border-outline-variant">
            <h3 className="font-semibold text-sm text-on-surface">
              Members {team && `(${team.length})`}
            </h3>
            <Button size="sm" onClick={() => setShowInvite(true)}>
              <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden>person_add</span>
              Invite
            </Button>
          </div>
          {isLoading ? (
            <TableSkeleton rows={4} cols={4} />
          ) : (
            <table className="w-full">
              <thead>
                <tr className="border-b border-outline-variant bg-surface-container-low">
                  {['Member', 'Role', 'Last Active', ''].map((h) => (
                    <th key={h} className="text-left px-4 py-2.5 font-mono text-[11px] text-on-surface-variant uppercase tracking-[0.06em]">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {team?.map((member) => (
                  <tr key={member.id} className="border-b border-outline-variant last:border-0 hover:bg-surface-container-low/50 transition-colors group">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <div
                          className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 text-xs font-bold"
                          style={{ background: member.avatarColor, color: member.avatarTextColor }}
                          aria-hidden
                        >
                          {member.initials}
                        </div>
                        <div>
                          <p className="text-sm font-medium text-on-surface">{member.name}</p>
                          <p className="text-xs text-on-surface-variant">{member.email}</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <RoleBadge role={member.role} />
                    </td>
                    <td className="px-4 py-3 text-xs text-on-surface-variant">{member.lastActive}</td>
                    <td className="px-4 py-3">
                      <Dropdown>
                        <DropdownTrigger asChild>
                          <button
                            className="p-1 rounded-lg hover:bg-surface-container transition-colors text-on-surface-variant opacity-0 group-hover:opacity-100"
                            aria-label={`Manage ${member.name}`}
                          >
                            <span className="material-symbols-outlined" style={{ fontSize: 16 }} aria-hidden>more_vert</span>
                          </button>
                        </DropdownTrigger>
                        <DropdownContent
                          items={[
                            { label: 'Change role', icon: 'manage_accounts', onClick: () => {} },
                            { label: 'Remove',      icon: 'person_remove',   onClick: () => {}, variant: 'danger' },
                          ]}
                        />
                      </Dropdown>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Permission matrix */}
        <div className="bg-white border border-outline-variant rounded-xl overflow-hidden">
          <div className="px-5 py-3.5 border-b border-outline-variant">
            <h3 className="font-semibold text-sm text-on-surface">Access Matrix</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-outline-variant bg-surface-container-low">
                  <th className="text-left px-4 py-2.5 font-mono text-[10px] text-on-surface-variant uppercase tracking-[0.06em]">Permission</th>
                  <th className="text-center px-4 py-2.5 font-mono text-[10px] text-secondary uppercase tracking-[0.06em]">Admin</th>
                  <th className="text-center px-4 py-2.5 font-mono text-[10px] text-on-surface-variant uppercase tracking-[0.06em]">Dev</th>
                </tr>
              </thead>
              <tbody>
                {PERMISSION_MATRIX.map((row) => (
                  <tr key={row.permission} className="border-b border-outline-variant last:border-0">
                    <td className="px-4 py-2.5 text-xs text-on-surface">{row.permission}</td>
                    <td className="px-4 py-2.5 text-center">
                      {row.admin
                        ? <span className="material-symbols-outlined sym-fill text-on-tertiary-container" style={{ fontSize: 16 }} aria-label="Allowed">check_circle</span>
                        : <span className="material-symbols-outlined text-outline-variant" style={{ fontSize: 16 }} aria-label="Not allowed">remove_circle</span>
                      }
                    </td>
                    <td className="px-4 py-2.5 text-center">
                      {row.developer
                        ? <span className="material-symbols-outlined sym-fill text-on-tertiary-container" style={{ fontSize: 16 }} aria-label="Allowed">check_circle</span>
                        : <span className="material-symbols-outlined text-outline-variant" style={{ fontSize: 16 }} aria-label="Not allowed">remove_circle</span>
                      }
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
