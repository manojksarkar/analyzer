import { lazy, Suspense, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClient } from './lib/queryClient'
import { ProjectLayout } from './components/shell/ProjectLayout'
import { ProtectedRoute } from './routes/ProtectedRoute'
import { ErrorBoundary } from './components/ErrorBoundary'
import { ToastProvider } from './components/ui/Toast'
import { Button } from './components/ui'
import { useAuthStore } from './store/auth'

// Code-split all pages
const SignInPage          = lazy(() => import('./pages/SignInPage').then((m) => ({ default: m.SignInPage })))
const ProjectsPage        = lazy(() => import('./pages/ProjectsPage').then((m) => ({ default: m.ProjectsPage })))
const NewProjectPage      = lazy(() => import('./pages/NewProjectPage').then((m) => ({ default: m.NewProjectPage })))
const ProjectDetailPage   = lazy(() => import('./pages/ProjectDetailPage').then((m) => ({ default: m.ProjectDetailPage })))
const DocumentsPage       = lazy(() => import('./pages/DocumentsPage').then((m) => ({ default: m.DocumentsPage })))
const DocumentInspectorPage = lazy(() => import('./pages/DocumentInspectorPage').then((m) => ({ default: m.DocumentInspectorPage })))
const ComparePage         = lazy(() => import('./pages/ComparePage').then((m) => ({ default: m.ComparePage })))
const VersionsPage        = lazy(() => import('./pages/VersionsPage').then((m) => ({ default: m.VersionsPage })))
const TeamPage            = lazy(() => import('./pages/TeamPage').then((m) => ({ default: m.TeamPage })))

function PageSpinner() {
  return (
    <div className="h-full flex items-center justify-center">
      <svg className="animate-spin h-6 w-6 text-secondary" fill="none" viewBox="0 0 24 24" aria-label="Loading">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
      </svg>
    </div>
  )
}

/** Blocks rendering until the persisted session is validated on app start. */
function AuthGate({ children }: { children: React.ReactNode }) {
  const bootstrapped = useAuthStore((s) => s.bootstrapped)
  const bootstrap = useAuthStore((s) => s.bootstrap)

  useEffect(() => {
    void bootstrap()
  }, [bootstrap])

  if (!bootstrapped) {
    return (
      <div className="h-screen flex items-center justify-center">
        <PageSpinner />
      </div>
    )
  }
  return <>{children}</>
}

function RootError() {
  return (
    <div className="h-screen flex flex-col items-center justify-center gap-4 text-center p-8">
      <div className="w-16 h-16 rounded-full bg-error/10 flex items-center justify-center">
        <span className="material-symbols-outlined text-error" style={{ fontSize: 32 }}>error_outline</span>
      </div>
      <div>
        <h1 className="text-lg font-semibold text-on-surface mb-1">Application error</h1>
        <p className="text-sm text-on-surface-variant">Reload the page to try again.</p>
      </div>
      <Button variant="outline" onClick={() => window.location.reload()}>
        <span className="material-symbols-outlined" style={{ fontSize: 16 }}>refresh</span>
        Reload
      </Button>
    </div>
  )
}

export default function App() {
  return (
    <ErrorBoundary fallback={<RootError />}>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AuthGate>
          <Suspense fallback={<PageSpinner />}>
            <Routes>
              {/* Public */}
              <Route path="/signin" element={<SignInPage />} />

              {/* Protected */}
              <Route
                path="/projects"
                element={
                  <ProtectedRoute>
                    <ProjectsPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/projects/new"
                element={
                  <ProtectedRoute>
                    <NewProjectPage />
                  </ProtectedRoute>
                }
              />

              {/* Project-scoped routes */}
              <Route
                path="/projects/:projectId/overview"
                element={
                  <ProtectedRoute>
                    <ProjectLayout breadcrumbLabel="Overview" />
                  </ProtectedRoute>
                }
              >
                <Route index element={<ProjectDetailPage />} />
              </Route>

              <Route
                path="/projects/:projectId/documents"
                element={
                  <ProtectedRoute>
                    <ProjectLayout breadcrumbLabel="Documents" />
                  </ProtectedRoute>
                }
              >
                <Route index element={<DocumentsPage />} />
              </Route>

              <Route
                path="/projects/:projectId/documents/:docId"
                element={
                  <ProtectedRoute>
                    <ProjectLayout
                      breadcrumbLabel="Document"
                      breadcrumbParentLabel="Documents"
                      breadcrumbParentTo="/projects/:projectId/documents"
                    />
                  </ProtectedRoute>
                }
              >
                <Route index element={<DocumentInspectorPage />} />
              </Route>

              <Route
                path="/projects/:projectId/compare"
                element={
                  <ProtectedRoute>
                    <ProjectLayout
                      breadcrumbLabel="Compare"
                      breadcrumbParentLabel="Documents"
                      breadcrumbParentTo="/projects/:projectId/documents"
                    />
                  </ProtectedRoute>
                }
              >
                <Route index element={<ComparePage />} />
              </Route>

              <Route
                path="/projects/:projectId/versions"
                element={
                  <ProtectedRoute>
                    <ProjectLayout breadcrumbLabel="Versions" />
                  </ProtectedRoute>
                }
              >
                <Route index element={<VersionsPage />} />
              </Route>

              <Route
                path="/projects/:projectId/team"
                element={
                  <ProtectedRoute>
                    <ProjectLayout breadcrumbLabel="Team" />
                  </ProtectedRoute>
                }
              >
                <Route index element={<TeamPage />} />
              </Route>

              {/* Fallbacks */}
              <Route path="/" element={<Navigate to="/projects" replace />} />
              <Route path="*" element={<Navigate to="/projects" replace />} />
            </Routes>
          </Suspense>
          </AuthGate>
        </BrowserRouter>
        <ToastProvider />
      </QueryClientProvider>
    </ErrorBoundary>
  )
}
