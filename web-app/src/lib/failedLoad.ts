/** The part of a React Query result a page needs to tell a failed read from an empty one. */
export interface LoadResult {
  isError: boolean
  error: unknown
  data: unknown
  isFetching: boolean
  refetch: () => Promise<unknown>
}

export interface FailedLoad {
  /** The first failure's error (its message is the API's). */
  error: unknown
  /** A retry is under way. */
  retrying: boolean
  /** Read every failed query again. */
  retry: () => void
}

/**
 * Did a read a page depends on fail, with nothing to show in its place? Then the page shows the
 * error and Retry, not its empty state ("No documents", "No changes"). A query that failed on a
 * background refetch still has its data, and keeps showing it.
 */
export function failedLoad(...queries: LoadResult[]): FailedLoad | null {
  const failed = queries.filter((q) => q.isError && q.data === undefined)
  if (!failed.length) return null
  return {
    error: failed[0].error,
    retrying: failed.some((q) => q.isFetching),
    retry: () => { for (const q of failed) void q.refetch() },
  }
}
