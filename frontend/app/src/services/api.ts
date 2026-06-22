import { PROJECTS, VERSIONS, DOCUMENTS, TEAM_MEMBERS, COMMITS } from '../data/mock'
import type { Project, Version, Document, TeamMember, Commit } from '../types'

const delay = (ms = 400) => new Promise((r) => setTimeout(r, ms))

export const projectsApi = {
  list: async (): Promise<Project[]> => {
    await delay()
    return PROJECTS
  },
  get: async (id: string): Promise<Project> => {
    await delay()
    const p = PROJECTS.find((p) => p.id === id)
    if (!p) throw new Error(`Project ${id} not found`)
    return p
  },
}

export const versionsApi = {
  list: async (_projectId: string): Promise<Version[]> => {
    await delay()
    return VERSIONS
  },
}

export const documentsApi = {
  list: async (_projectId: string): Promise<Document[]> => {
    await delay()
    return DOCUMENTS
  },
}

export const teamApi = {
  list: async (_projectId: string): Promise<TeamMember[]> => {
    await delay()
    return TEAM_MEMBERS
  },
}

export const commitsApi = {
  list: async (_projectId: string): Promise<Commit[]> => {
    await delay()
    return COMMITS
  },
}
