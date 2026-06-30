import { repositoriesApi, usersApi } from '../services/api'

/**
 * Imperative repo/user actions for the new-project wizard. These are one-shot
 * commands (test connection, browse the tree, upload a build-config file, search
 * the org directory) rather than cached reads, so they're exposed as plain async
 * functions — but routed through a hook so the page never imports the service
 * layer directly (see CONVENTIONS.md §3).
 */
export function useRepositoryWizard() {
  return {
    testConnection: repositoriesApi.testConnection,
    browse: repositoriesApi.browse,
    upload: repositoriesApi.upload,
    searchUsers: usersApi.search,
  }
}
