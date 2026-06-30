import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

/**
 * Two test "projects":
 *  - `unit` — hermetic UI tests (mappers, components, hooks). jsdom + MSW
 *             (src/test/setup.ts) intercepts HTTP and serves committed fixtures,
 *             so this suite needs NO backend and runs offline.
 *  - `api`  — live API validation. No MSW; the runner hits a real server
 *             (VITE_API_URL / API_TEST_URL) and validates each response against
 *             the zod schemas. Auto-skips when no server is reachable.
 *
 * Run all UI tests:        npm test
 * Validate the live API:   npm run test:api   (mock or real, env-selected)
 */
export default defineConfig({
  test: {
    projects: [
      {
        plugins: [react()],
        test: {
          name: 'unit',
          environment: 'jsdom',
          globals: false,
          css: false,
          setupFiles: ['./src/test/setup.ts'],
          include: ['src/**/*.test.{ts,tsx}'],
          exclude: ['src/test/api/**'],
        },
      },
      {
        test: {
          name: 'api',
          // jsdom (not node) so importing the mappers' http→store chain finds a
          // localStorage; the runner uses its own fetch, never MSW.
          environment: 'jsdom',
          include: ['src/test/api/**/*.test.ts'],
          testTimeout: 30000,
          hookTimeout: 30000,
        },
      },
    ],
  },
})
