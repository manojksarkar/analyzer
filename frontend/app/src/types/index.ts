export type UserRole = 'admin' | 'developer'

export type DocStatus = 'in_review' | 'approved' | 'complete' | 'draft' | 'unchanged'
export type VersionStatus = 'in_review' | 'approved' | 'complete'
export type PageState = 'never' | 'running' | 'in_review' | 'complete' | 'stale'

export interface TeamMember {
  id: string
  name: string
  initials: string
  email: string
  role: UserRole
  lastActive: string
  avatarColor: string
  avatarTextColor: string
  pending?: boolean
}

export interface Project {
  id: string
  name: string
  icon: string
  repoPath: string
  standard: string
  latestVersion: string | null
  inReviewCount: number
  progress: number
  lastRun: string | null
  team: TeamMember[]
  userRole: UserRole
  pageState: PageState
}

export interface Version {
  tag: string
  status: VersionStatus
  description: string
  sha: string
  shortSha: string
  branch: string
  docsCount: number
  date: string
  pageState: PageState
  newCommitsSince?: number
}

export interface Commit {
  sha: string
  shortSha: string
  message: string
  author: string
  relativeTime: string
  branch: string
  versionTag?: string
  pageState: PageState
}

export interface Document {
  id: string
  name: string
  process: string
  status: DocStatus
  assignee?: string
  version: string
  updatedAt: string
  subtitle?: string
  due?: string
  assigneeInitials?: string
  assigneeColor?: string
  assigneeTextColor?: string
}
