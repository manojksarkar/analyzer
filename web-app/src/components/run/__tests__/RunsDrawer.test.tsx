import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { RunsDrawer } from '../RunsDrawer'

/* The Runs drawer (Versions page → View runs): how a version was made, run by run -- this server's
   settings at each run's start, newest first, the one at work marked; no secret in any of it. */

const RUN = {
  at: '2026-10-28T09:14:02Z', host: 'build-01', code: '782d749', phases: [1, 1], components: null,
  llmServer: { provider: 'anthropic', defaultModel: 'claude-sonnet-5-5', baseUrl: 'https://api.anthropic.com', apiKey: 'set' },
  speedups: { llms: [{ name: 'claude-a', maxConcurrent: 2 }], pacing: 'after', parseWorkers: 'auto -> 4' },
  llvm: { libPath: 'C:/LLVM/bin/libclang.dll' },
}

function setup(body: { running: boolean; runs: unknown[] }) {
  server.use(http.get(`${API_BASE_URL}/projects/p1/versions/ver1/run-settings`,
    () => HttpResponse.json({ version_id: 'ver1', ...body })))
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <RunsDrawer projectId="p1" versionId="ver1" versionTag="v1.2.0" onClose={() => {}} />
    </QueryClientProvider>,
  )
}

describe('RunsDrawer', () => {
  it('shows each run’s settings, the one at work marked', async () => {
    setup({ running: true, runs: [RUN, { ...RUN, at: '2026-10-28T09:20:45Z', phases: [2, null], components: ['Layer1.Math'] }] })
    expect(await screen.findByText('Derive · Views · Documents')).toBeInTheDocument()
    expect(screen.getByRole('dialog', { name: 'Runs' })).toHaveTextContent('v1.2.0 · 2 runs')
    expect(screen.getAllByText('Running now')).toHaveLength(1)
    expect(screen.getAllByText('anthropic / claude-sonnet-5-5')).toHaveLength(2)
    expect(screen.getAllByText('claude-a (2 at once)')).toHaveLength(2)
    expect(screen.getAllByText('auto → 4 files at once')).toHaveLength(2)
    expect(screen.getAllByText('API key set')).toHaveLength(2)
    expect(screen.getByText('Layer1.Math')).toBeInTheDocument()
    expect(screen.getByText('Keys and header values are never recorded.')).toBeInTheDocument()
  })

  it('says when a version has no runs recorded', async () => {
    setup({ running: false, runs: [] })
    expect(await screen.findByText(/Made before runs were recorded/)).toBeInTheDocument()
    expect(screen.queryByText('Running now')).not.toBeInTheDocument()
  })
})
