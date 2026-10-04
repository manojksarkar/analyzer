import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ProjectRow } from '../components/ProjectRow'
import type { Project } from '../../../types'

/* #37: a project with no members showed an "Add" button that did nothing. It opens the Team page
   now, for the admin (who can add); anyone else sees no button. */

function setup(role: 'admin' | 'developer') {
  const project = {
    id: 'p1', name: 'Brake ECU', icon: 'memory', standard: 'ISO 26262', latestVersion: 'v1.2.0', inReviewCount: 0,
    progress: 0, lastRun: null, pageState: 'complete', team: [], userRole: role,
  } as unknown as Project
  const onNavigate = vi.fn()
  const onTeam = vi.fn()
  render(
    <QueryClientProvider client={new QueryClient()}>
      <table><tbody><ProjectRow project={project} onNavigate={onNavigate} onTeam={onTeam} /></tbody></table>
    </QueryClientProvider>,
  )
  return { project, onNavigate, onTeam }
}

describe('ProjectRow: Add team members', () => {
  it("opens the project's Team page for an admin, not the project", async () => {
    const { project, onNavigate, onTeam } = setup('admin')
    await userEvent.setup().click(screen.getByRole('button', { name: `Add team members to ${project.name}` }))
    expect(onTeam).toHaveBeenCalledWith(project.id)
    expect(onNavigate).not.toHaveBeenCalled()
  })

  it('is not offered to a developer', () => {
    setup('developer')
    expect(screen.queryByRole('button', { name: /Add team members/ })).not.toBeInTheDocument()
  })
})
