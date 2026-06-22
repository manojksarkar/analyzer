import { Suspense } from 'react'
import { Outlet, useParams } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'
import { Subbar } from './Subbar'
import { ErrorBoundary } from '../ErrorBoundary'
import { Skeleton } from '../ui'
import { useProject, useVersions } from '../../hooks/useProjects'

interface ProjectLayoutProps {
  breadcrumbLabel: string
  breadcrumbParentLabel?: string
  breadcrumbParentTo?: string
}

function PageSkeleton() {
  return (
    <div className="p-6 space-y-4">
      <Skeleton className="h-8 w-48" />
      <div className="grid grid-cols-3 gap-4">
        {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-32" />)}
      </div>
      <Skeleton className="h-64" />
    </div>
  )
}

export function ProjectLayout({ breadcrumbLabel, breadcrumbParentLabel, breadcrumbParentTo }: ProjectLayoutProps) {
  const { projectId } = useParams<{ projectId: string }>()

  const { data: project } = useProject(projectId ?? '')
  const { data: versions } = useVersions(projectId ?? '')
  const latestVersion = versions?.[0]

  const breadcrumbs = breadcrumbParentLabel
    ? [
        { label: breadcrumbParentLabel, to: breadcrumbParentTo },
        { label: breadcrumbLabel },
      ]
    : [
        { label: project?.name ?? '…', to: `/projects/${projectId}/overview` },
        { label: breadcrumbLabel },
      ]

  return (
    <div className="h-screen flex overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <Topbar breadcrumbs={breadcrumbs} />
        <Subbar
          projectName={project?.name ?? '…'}
          selectedVersion={latestVersion}
        />
        <div className="flex-1 overflow-hidden">
          <ErrorBoundary>
            <Suspense fallback={<PageSkeleton />}>
              <Outlet />
            </Suspense>
          </ErrorBoundary>
        </div>
      </div>
    </div>
  )
}
