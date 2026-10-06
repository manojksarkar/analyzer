import { Navigate } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuthStore } from '../store/auth'

/* A page for superusers only (Live logs). Anyone else lands on Projects: the menu entry and the
   links to it are hidden from them, so only a typed address gets here. The API refuses them too. */
export function SuperuserRoute({ children }: { children: ReactNode }) {
  const isSuperuser = useAuthStore((s) => !!s.user?.isSuperuser)
  if (!isSuperuser) return <Navigate to="/projects" replace />
  return <>{children}</>
}
