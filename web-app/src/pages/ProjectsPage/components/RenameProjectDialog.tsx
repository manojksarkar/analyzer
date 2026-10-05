import { useState, type FormEvent } from 'react'
import { Button, Icon, Input, Modal, Text } from '../../../components/ui'
import { useUpdateProject } from '../../../hooks/useProjects'

/* Rename a project (its admins; PATCH /projects/{id} {name}) -- from its row's menu on the
   Projects page: a rename is rare, so it is not on the project's own pages. The new name shows
   everywhere at once. Documents already made keep the name they were made with -- on their
   cover and in their introduction, in the Word file and on the page, which reads like it --
   until a re-export or a new run. Opened by the page, not inside the row: a click in a dialog
   the row owned would reach the row and open the project. */

// The server's limit (api/routes/projects.py MAX_PROJECT_NAME).
const MAX_NAME = 120

export function RenameProjectDialog({ project, otherNames, onClose }: {
  project: { id: string; name: string }
  /** The names of the other projects in the list: the same name again is said, not refused
   *  (the server allows it), so two rows do not end up looking alike by accident. */
  otherNames: string[]
  onClose: () => void
}) {
  const [value, setValue] = useState(project.name)
  const rename = useUpdateProject(project.id)
  const next = value.trim()
  const problem = !next ? 'A project needs a name.'
    : next.length > MAX_NAME ? `A project name is at most ${MAX_NAME} characters.` : null
  const unchanged = next === project.name
  const taken = !problem && !unchanged && otherNames.some((n) => n.trim().toLowerCase() === next.toLowerCase())

  function submit(e: FormEvent) {
    e.preventDefault()
    if (problem || unchanged || rename.isPending) return
    rename.mutate({ name: next }, { onSuccess: onClose })
  }

  return (
    <Modal open onClose={onClose} title="Rename project" className="max-w-[440px]">
      <form onSubmit={submit} className="-mt-3">
        <Input
          id="rename-project-name"
          label="Project name"
          value={value}
          autoFocus
          maxLength={MAX_NAME + 40}
          onFocus={(e) => e.currentTarget.select()}
          onChange={(e) => setValue(e.target.value)}
          error={value !== project.name && problem ? problem : undefined}
        />
        {taken && (
          <p className="mt-1 flex items-center gap-1 text-xs text-[#b45309]" role="status">
            <Icon name="info" size={12} />Another project is already called “{next}”.
          </p>
        )}
        <Text as="p" variant="caption" className="mt-3 leading-relaxed">
          Documents already made keep the name they were made with, on their cover and in their
          introduction. A re-export or a new run uses the new name.
        </Text>
        <div className="flex justify-end gap-2 pt-4 mt-4 -mx-6 px-6 border-t border-outline-variant">
          <Button type="button" variant="outline" size="sm" onClick={onClose}>Cancel</Button>
          <Button type="submit" size="sm" loading={rename.isPending} disabled={!!problem || unchanged}>
            <Icon name="edit" size={14} />Rename
          </Button>
        </div>
      </form>
    </Modal>
  )
}
