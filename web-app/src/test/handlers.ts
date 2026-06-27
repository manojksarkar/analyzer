import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../lib/http'
import projects from './fixtures/projects.json'

/**
 * MSW request handlers for the hermetic (unit) suite. They answer the exact
 * endpoints the UI calls from committed fixtures, so component/hook tests never
 * touch a real backend. Add a handler here as you cover more pages; unhandled
 * requests fail loudly (see src/test/setup.ts `onUnhandledRequest: 'error'`).
 */
export const handlers = [
  http.get(`${API_BASE_URL}/projects`, () => HttpResponse.json(projects)),
]
