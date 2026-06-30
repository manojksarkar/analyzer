/**
 * Boundary mappers: API (snake_case, server shapes) → frontend types.
 *
 * This is the only place that knows the wire format. Components keep using the
 * existing camelCase types unchanged; UI-only fields with no API source (icon,
 * avatar colours, progress) are derived deterministically here. One file per
 * domain — this barrel re-exports them all. Every mismatch is logged in
 * web-app/INTEGRATION_NOTES.md.
 */
export * from './auth'
export * from './project'
export * from './version'
export * from './commit'
export * from './document'
export * from './member'
export * from './job'
export * from './notification'
export * from './compare'
