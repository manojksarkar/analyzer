import { setupServer } from 'msw/node'
import { handlers } from './handlers'

/** Shared MSW server for the unit suite (started/stopped in setup.ts). */
export const server = setupServer(...handlers)
