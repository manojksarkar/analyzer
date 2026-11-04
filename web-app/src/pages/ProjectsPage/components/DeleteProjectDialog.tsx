import { useState, type FormEvent } from 'react'
import { Button, Icon, Input, Modal, Text } from '../../../components/ui'
import { useDeleteProject } from '../../../hooks/useProjects'

/* Delete a project (its admins; DELETE /projects/{id}) from its row's menu on the Projects page
   (docs/ui-mockups/projects.html, BACKLOG NW-4). Everything of it goes, so its name is typed to
   turn Delete on: a mis-click deletes nothing. Refused while a run of the project is going (409,
   said in a toast by the hook). Opened by the page, not inside the row, as Rename is: a click in a
   dialog the row owned would reach the row and open the project. */

export function DeleteProjectDialog({ project, onClose }: {
  project: { id: string; name: string }
  onClose: () => void
}) {
  const [typed, setTyped] = useState('')
  const remove = useDeleteProject()
  const matches = typed.trim() === project.name.trim()

  function submit(e: FormEvent) {
    e.preventDefault()
    if (!matches || remove.isPending) return
    // Closed either way: deleted, or refused with the reason in a toast.
    remove.mutate(project.id, { onSettled: onClose })
  }

  return (
    <Modal open onClose={onClose} title="Delete project" className="max-w-[440px]">
      <form onSubmit={submit} className="-mt-3">
        <p className="text-sm text-on-surface">Delete <strong>{project.name}</strong>?</p>
        <Text as="p" variant="caption" className="mt-2 leading-relaxed">
          Everything of it goes: its versions, documents, diagrams and approved copies, and the code
          checked out for it. This cannot be undone.
        </Text>
        <div className="mt-3.5">
          <Input
            id="delete-project-name"
            label="Type the project name to delete it"
            value={typed}
            autoFocus
            autoComplete="off"
            spellCheck={false}
            onChange={(e) => setTyped(e.target.value)}
          />
        </div>
        <div className="flex justify-end gap-2 pt-4 mt-4 -mx-6 px-6 border-t border-outline-variant">
          <Button type="button" variant="outline" size="sm" onClick={onClose}>Cancel</Button>
          <Button type="submit" size="sm" loading={remove.isPending} disabled={!matches}
                  className="bg-error text-on-status border border-error hover:bg-error/90">
            <Icon name="delete" size={14} />Delete
          </Button>
        </div>
      </form>
    </Modal>
  )
}
