import { useState } from 'react'
import { useInviteMember, useUserSearch } from '../../../hooks/useTeamMutations'
import { Avatar, Button, Icon, Modal, Skeleton, Text, toast } from '../../../components/ui'
import { cn } from '../../../lib/cn'
import { copyText } from '../../../lib/clipboard'
import type { TeamMember, UserRole } from '../../../types'

/* Add a person to the project (A20): search everyone with an account by name or email and pick
   one, or type the address of someone with no account, who gets one. Either way they are an
   active member at once, ready to be assigned. A new account's temporary password is shown here,
   once. */

interface Person { id: string | null; name: string; email: string; initials: string }

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const ROW = 'w-full flex items-center gap-2.5 px-2.5 py-2 rounded-xl border text-left transition-colors'

function PersonText({ name, sub }: { name: string; sub: string }) {
  return (
    <span className="flex-1 min-w-0">
      <span className="block text-body text-on-surface truncate">{name}</span>
      <span className="block font-mono text-label text-outline truncate mt-px">{sub}</span>
    </span>
  )
}

export function AddMemberDialog({
  projectId, projectName, members, onClose,
}: {
  projectId: string
  projectName?: string
  /** The project's members: the people already in it cannot be picked again. */
  members: TeamMember[]
  onClose: () => void
}) {
  const [query, setQuery] = useState('')
  const [picked, setPicked] = useState<Person | null>(null)
  const [role, setRole] = useState<UserRole>('developer')
  // An account this made: its temporary password, shown once
  const [created, setCreated] = useState<{ email: string; password: string } | null>(null)
  const { data: found, isLoading } = useUserSearch(query, !picked)
  const invite = useInviteMember(projectId)

  const inTeam = new Set(members.filter((m) => !m.pending && m.userId).map((m) => m.userId))
  const people = found ?? []
  const typed = query.trim().toLowerCase()
  // A whole address nobody has: offered as a new account
  const newAddress = EMAIL.test(typed) && !people.some((u) => u.email.toLowerCase() === typed) ? typed : null
  const newPerson = (email: string): Person => ({ id: null, name: email, email, initials: '' })
  const firstFree = people.find((u) => !inTeam.has(u.id))

  function add() {
    if (!picked) return
    invite.mutate({ email: picked.email, role }, {
      onSuccess: (r) => {
        if (r.temporaryPassword) setCreated({ email: r.email, password: r.temporaryPassword })
        else onClose()
      },
    })
  }

  if (created) {
    return (
      <Modal open onClose={onClose} title="Account created" description={created.email} className="max-w-[440px]">
        <div className="-mt-3 space-y-3">
          <Text as="p" variant="body" className="text-on-surface-variant">
            They had no account, so one was made. Pass on this temporary password; they change it after signing in. It is not shown again.
          </Text>
          <div className="flex items-center gap-2">
            <code className="flex-1 px-3 py-2 rounded-lg bg-surface-container-low border border-outline-variant font-mono text-sm text-on-surface select-all">{created.password}</code>
            <Button variant="outline" size="sm" onClick={() => {
              void copyText(created.password).then((ok) => ok ? toast.success('Copied', 'The temporary password is on the clipboard.')
                : toast.error('Copy failed', 'Select the password and copy it by hand.'))
            }}>
              <Icon name="content_copy" size={14} />Copy
            </Button>
          </div>
        </div>
        <div className="flex justify-end pt-4 mt-4 -mx-6 px-6 border-t border-outline-variant">
          <Button size="sm" onClick={onClose}>Done</Button>
        </div>
      </Modal>
    )
  }

  return (
    <Modal open onClose={onClose} title="Add to project" description={projectName} className="max-w-[460px]">
      <div className="-mt-3 space-y-4">
        {picked ? (
          <div className={cn(ROW, 'border-secondary bg-surface-container-low')}>
            <Avatar person={picked.id ? { userId: picked.id, name: picked.name, initials: picked.initials } : null} size={28} />
            <PersonText
              name={picked.name}
              sub={picked.id ? picked.email : 'No account yet: one is made'}
            />
            <button
              type="button"
              onClick={() => setPicked(null)}
              aria-label="Pick someone else"
              title="Pick someone else"
              className="p-1 rounded-lg hover:bg-surface-container text-on-surface-variant transition-colors"
            >
              <Icon name="close" size={16} />
            </button>
          </div>
        ) : (
          <div>
            <label htmlFor="add-member-search" className="block text-on-surface-variant uppercase mb-1.5 font-mono text-caption font-semibold tracking-[0.06em]">
              Name or email
            </label>
            <input
              id="add-member-search"
              autoFocus
              autoComplete="off"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key !== 'Enter') return
                e.preventDefault()
                if (firstFree) setPicked(firstFree)
                else if (newAddress) setPicked(newPerson(newAddress))
              }}
              placeholder="Search people, or type an email"
              className="w-full h-11 px-3 border border-outline-variant rounded-xl bg-surface-container-lowest focus:outline-none focus:border-secondary text-sm"
            />
            <div className="mt-2 max-h-[264px] overflow-y-auto space-y-1.5 pr-0.5">
              {isLoading && Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-11" />)}
              {people.map((u) => {
                const member = inTeam.has(u.id)
                return (
                  <button
                    key={u.id}
                    type="button"
                    disabled={member}
                    onClick={() => setPicked(u)}
                    className={cn(ROW, 'border-outline-variant', member ? 'opacity-60 cursor-default' : 'hover:border-secondary hover:bg-surface')}
                  >
                    <Avatar person={{ userId: u.id, name: u.name, initials: u.initials }} size={28} />
                    <PersonText name={u.name} sub={u.email} />
                    {member && <span className="font-mono text-label text-outline flex-shrink-0">Member</span>}
                  </button>
                )
              })}
              {newAddress && (
                <button
                  type="button"
                  onClick={() => setPicked(newPerson(newAddress))}
                  className={cn(ROW, 'border-dashed border-outline-variant hover:border-secondary hover:bg-surface')}
                >
                  <Avatar person={null} size={28} />
                  <PersonText name={`Add ${newAddress}`} sub="No account yet: one is made" />
                  <Icon name="person_add" size={16} className="text-secondary flex-shrink-0" />
                </button>
              )}
              {!isLoading && people.length === 0 && !newAddress && (
                <Text as="p" variant="caption" className="font-mono px-1">
                  {typed ? 'Nobody matches. Type their whole email address to add someone new.' : 'Nobody else has an account. Type an email address to add someone.'}
                </Text>
              )}
            </div>
          </div>
        )}
        <div className="flex items-center gap-5">
          {(['developer', 'admin'] as UserRole[]).map((r) => (
            <label key={r} className="flex items-center gap-2 cursor-pointer">
              <input type="radio" name="add-member-role" checked={role === r} onChange={() => setRole(r)} className="accent-secondary" />
              <span className="text-on-surface text-body">{r === 'admin' ? 'Admin' : 'Developer'}</span>
            </label>
          ))}
        </div>
      </div>
      <div className="flex justify-end gap-2 pt-4 mt-4 -mx-6 px-6 border-t border-outline-variant">
        <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
        <Button size="sm" loading={invite.isPending} disabled={!picked} onClick={add}>
          <Icon name="person_add" size={14} />Add
        </Button>
      </div>
    </Modal>
  )
}
