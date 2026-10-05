import { QueryClient } from '@tanstack/react-query'
import { isRetryable } from './http'

/** One more try for a read the network or the server failed (5xx); none for a 4xx answer
 *  (401, 403, 404, …), which is the same the second time and only delayed the error page. */
export const retryQuery = (failureCount: number, error: unknown): boolean =>
  failureCount < 1 && isRetryable(error)

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5,
      retry: retryQuery,
      refetchOnWindowFocus: false,
    },
  },
})
