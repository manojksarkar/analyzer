/**
 * Service layer — thin wrappers over the HTTP client that unwrap the API's
 * response envelopes and map wire shapes to frontend types (see ../mappers).
 *
 * One file per domain; this barrel re-exports the `*Api` objects + their input
 * types under the same names hooks already import from `services/api`.
 */
export * from './auth'
export * from './projects'
export * from './repositories'
export * from './users'
export * from './versions'
export * from './commits'
export * from './documents'
export * from './team'
export * from './jobs'
export * from './compare'
export * from './notifications'
