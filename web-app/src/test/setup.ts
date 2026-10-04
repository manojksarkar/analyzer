import '@testing-library/jest-dom/vitest'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { cleanup, configure } from '@testing-library/react'
import { server } from './server'

// findBy / waitFor give up after 1 s by default: a page that reads several queries took longer
// on a busy machine (a browser running beside the suite), and a passing test failed.
configure({ asyncUtilTimeout: 4000 })

// Fail tests that hit an endpoint we haven't mocked, so coverage gaps surface.
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  cleanup()
  server.resetHandlers()
})
afterAll(() => server.close())
