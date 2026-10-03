import { Suspense, useState } from 'react'
import { Outlet, useLocation, useParams } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'
import { Subbar, VersionStatusChip } from './Subbar'
import { SubbarCtaProvider } from './SubbarCta'
import { ErrorBoundary } from '../ErrorBoundary'
import { Skeleton } from '../ui'
import { useProject, useVersions, useCommits, useDocument } from '../../hooks/useProjects'
import { useProjectViewState } from '../../hooks/useProjectViewState'

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
  const { projectId, docId } = useParams<{ projectId: string; docId?: string }>()
  const { pathname } = useLocation()

  const { data: project } = useProject(projectId ?? '')
  // A document page's last crumb names the document (mockup: "SWE.3 — Brake Controller");
  // shared with the page's own query, so no second request.
  const { data: doc } = useDocument(projectId ?? '', docId ?? '')
  const { data: versions } = useVersions(projectId ?? '')
  const { data: commits } = useCommits(projectId ?? '')
  const latestVersion = versions?.[0]
  // Default latest commit so the picker renders even before any version exists.
  const latestCommit = commits?.[0]

  // Subbar status reflects the picker selection (and any live run) — shared with
  // the detail page via useProjectViewState.
  const { pageState, viewVersion, isLoading: viewLoading } = useProjectViewState(projectId ?? '')
  // The Subbar's action slot, filled by the page through <SubbarCta>.
  const [ctaSlot, setCtaSlot] = useState<HTMLDivElement | null>(null)

  // The project always leads (it was dropped whenever a page had a parent crumb).
  const breadcrumbs = [
    { label: project?.name ?? '…', to: `/projects/${projectId}/overview` },
    ...(breadcrumbParentLabel
      ? [{ label: breadcrumbParentLabel, to: breadcrumbParentTo?.replace(':projectId', projectId ?? '') }]
      : []),
    { label: doc ? `${doc.process} — ${doc.name}` : breadcrumbLabel },
  ]

  return (
    <div className="h-screen flex overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <Topbar breadcrumbs={breadcrumbs} />
        <Subbar
          projectName={project?.name ?? '…'}
          selectedVersion={latestVersion}
          selectedCommit={latestCommit}
          statusBadge={
            viewLoading
              ? <Skeleton className="h-5 w-20 rounded-full" />
              : project
                ? <VersionStatusChip state={pageState} version={viewVersion} />
                : undefined
          }
          ctaSlotRef={setCtaSlot}
        />
        <div className="flex-1 flex flex-col overflow-hidden min-h-0">
          {/* The layout outlives navigation between a project's pages: without the reset, one
              crash kept the error screen on every page after it. */}
          <ErrorBoundary resetKey={pathname}>
            <Suspense fallback={<PageSkeleton />}>
              <SubbarCtaProvider slot={ctaSlot}>
                <Outlet />
              </SubbarCtaProvider>
            </Suspense>
          </ErrorBoundary>
        </div>
      </div>
    </div>
  )
}
