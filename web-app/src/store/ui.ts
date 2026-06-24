import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface UIState {
  sidebarCollapsed: boolean
  toggleSidebar: () => void
  setSidebarCollapsed: (v: boolean) => void
  /** Per-project selected commit/version sha (drives the detail view). In-memory only. */
  selectedRef: Record<string, string>
  setSelectedRef: (projectId: string, sha: string) => void
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setSidebarCollapsed: (v) => set({ sidebarCollapsed: v }),
      selectedRef: {},
      setSelectedRef: (projectId, sha) =>
        set((s) => ({ selectedRef: { ...s.selectedRef, [projectId]: sha } })),
    }),
    // Only persist the sidebar; selection resets on reload.
    { name: 'ui', partialize: (s) => ({ sidebarCollapsed: s.sidebarCollapsed }) }
  )
)
