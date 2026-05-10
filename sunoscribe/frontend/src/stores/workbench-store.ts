import { create } from 'zustand'

import type { UncertainNoteDiagnosis } from '@/types/agents'

interface WorkbenchState {
  selectedProjectId: string | null
  selectedRevisionId: string | null
  selectedNote: UncertainNoteDiagnosis | null
  setSelectedProjectId: (projectId: string | null) => void
  setSelectedRevisionId: (revisionId: string | null) => void
  setSelectedNote: (note: UncertainNoteDiagnosis | null) => void
}

export const useWorkbenchStore = create<WorkbenchState>((set) => ({
  selectedProjectId: null,
  selectedRevisionId: null,
  selectedNote: null,
  setSelectedProjectId: (selectedProjectId) => set({ selectedProjectId }),
  setSelectedRevisionId: (selectedRevisionId) => set({ selectedRevisionId }),
  setSelectedNote: (selectedNote) => set({ selectedNote }),
}))
