import { projectsApi, repositoriesApi, usersApi } from '../services/api'

/** One object for every render: the wizard's org-directory search lists it in an effect's
 *  dependencies, and a new object each render re-ran that search after every answer -- GET
 *  /users/search without end while "Add member" was open. */
const ACTIONS = {
  testConnection: repositoriesApi.testConnection,
  browse: repositoriesApi.browse,
  upload: repositoriesApi.upload,
  searchUsers: usersApi.search,
  previewConfig: projectsApi.previewConfig,
}

/**
 * Imperative repo/user actions for the new-project wizard. These are one-shot
 * commands (test connection, browse the tree, upload a build-config file, search
 * the org directory) rather than cached reads, so they're exposed as plain async
 * functions — but routed through a hook so the page never imports the service
 * layer directly (see the ui-dev skill, §3 Data & state).
 */
export function useRepositoryWizard() {
  return ACTIONS
}
