import { useState, type FormEvent } from 'react'
import { Button, Icon, Input, Modal, Text } from '../ui'
import { useUpdateProject } from '../../hooks/useProjects'

/* Rename a project (its admins; PATCH /projects/{id} {name}). The new name shows everywhere at
   once. Documents already made keep the name they were made with -- on their cover and in their
   introduction, in the Word file and on the page, which reads like it -- until a re-export or a
   new run. Opened from the Subbar's project menu. */

// The server's limit (api/routes/projects.py MAX_PROJECT_NAME).
const MAX_NAME = 120

export function RenameProjectDialog({ projectId, name, onClose }: {
  projectId: string
  /** The current name. */
  name: string
  onClose: () => void
}) {
  const [value, setValue] = useState(name)
  const rename = useUpdateProject(projectId)
  const next = value.trim()
  const problem = !next ? 'A project needs a name.'
    : next.length > MAX_NAME ? `A project name is at most ${MAX_NAME} characters.` : null
  const unchanged = next === name

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
          onFocus={(e) => e.currentTarget.select()}
          onChange={(e) => setValue(e.target.value)}
          error={value !== name && problem ? problem : undefined}
        />
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
