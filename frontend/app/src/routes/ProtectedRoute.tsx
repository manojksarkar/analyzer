import { Navigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '../store/auth'
import type { ReactNode } from 'react'

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const location = useLocation()

  if (!isAuthenticated) {
    return <Navigate to="/signin" state={{ from: location }} replace />
  }

  return <>{children}</>
}
