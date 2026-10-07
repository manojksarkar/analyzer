import { create } from 'zustand'

/** The Overview's Run Analysis dialog. The page opens it, and so does a failed run's Re-run in
 *  Needs attention (components/attention/), which is on every project page and goes to the
 *  Overview first. The page closes it when it leaves, so it never opens by itself later. */
interface RunModalStore {
  open: boolean
  openRun: () => void
  close: () => void
}

export const useRunModal = create<RunModalStore>((set) => ({
  open: false,
  openRun: () => set({ open: true }),
  close: () => set({ open: false }),
}))
