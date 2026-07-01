import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/**
 * Picker selection. Versions are keyed by their backend id (a re-run on the
 * same commit produces a new id but reuses the sha), commits by sha. Resolving
 * a version by id — not sha — is what lets the documents re-scope when two
 * versions share a commit.
 */
export type Selection =
  | { type: 'version'; id: string }
  | { type: 'commit'; sha: string }

interface UIState {
  sidebarCollapsed: boolean
  toggleSidebar: () => void
  setSidebarCollapsed: (v: boolean) => void
  /** Document Inspector's right Review-status / outline panel collapse state. */
  inspectorPanelCollapsed: boolean
  toggleInspectorPanel: () => void
  /** Per-project picker selection (drives the detail view). In-memory only. */
  selectedRef: Record<string, Selection>
  setSelectedRef: (projectId: string, sel: Selection) => void
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setSidebarCollapsed: (v) => set({ sidebarCollapsed: v }),
      inspectorPanelCollapsed: false,
      toggleInspectorPanel: () => set((s) => ({ inspectorPanelCollapsed: !s.inspectorPanelCollapsed })),
      selectedRef: {},
      setSelectedRef: (projectId, sel) =>
        set((s) => ({ selectedRef: { ...s.selectedRef, [projectId]: sel } })),
    }),
    // Persist the collapse states; selection resets on reload.
    {
      name: 'ui',
      partialize: (s) => ({
        sidebarCollapsed: s.sidebarCollapsed,
        inspectorPanelCollapsed: s.inspectorPanelCollapsed,
      }),
    }
  )
)
