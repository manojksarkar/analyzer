import { Button, Icon, Modal } from '../../../components/ui'
import type { MemberChange } from '../helpers'

/* Ask before a member is removed, or before an admin takes their own admin role away: either
   can lock someone out of the project, and one click must not do it. */

export function ConfirmMemberChange({ change, isMe, projectName, busy, onConfirm, onClose }: {
  change: MemberChange
  /** The member is the signed-in user. */
  isMe: boolean
  projectName?: string
  busy: boolean
  onConfirm: () => void
  onClose: () => void
}) {
  const { action, member } = change
  const where = projectName ?? 'this project'
  const title = action === 'demote'
    ? 'Make yourself a Developer?'
    : isMe ? 'Remove yourself from the project?' : `Remove ${member.name}?`
  const body = action === 'demote'
    ? `You will no longer manage the team, run the analysis, assign reviewers or approve documents in ${where}. Only another admin can make you an admin again.`
    : isMe
      ? `You will lose access to ${where}. Only an admin can add you again.`
      : `${member.name} will lose access to ${where}. The documents they review that are not approved go back to Needs a reviewer.`
  return (
    <Modal open onClose={onClose} title={title} className="max-w-[440px]">
      <p className="-mt-3 text-xs text-on-surface leading-relaxed">{body}</p>
      <div className="flex justify-end gap-2 pt-4 mt-4 -mx-6 px-6 border-t border-outline-variant">
        <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
        <Button variant="danger" size="sm" loading={busy} onClick={onConfirm}>
          <Icon name={action === 'demote' ? 'remove_moderator' : 'person_remove'} size={14} />
          {action === 'demote' ? 'Make me a Developer' : 'Remove'}
        </Button>
      </div>
    </Modal>
  )
}
