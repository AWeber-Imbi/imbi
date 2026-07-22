import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '@/api/client'
import { GraphQueryProvider } from '@/contexts/GraphQueryContext'
import { ThemeProvider } from '@/contexts/ThemeContext'
import type { GraphQueryResult } from '@/types'

// Stubs live in ../__mocks__/ so vitest's auto-mock convention picks them up.
vi.mock('../CypherEditor')
vi.mock('../ResultGraph')
vi.mock('../SchemaPanel')

import { GraphQueryWorkbench } from '../GraphQueryWorkbench'

const SAMPLE_RESULT: GraphQueryResult = {
  columns: ['n'],
  edges: [],
  elapsed_ms: 7,
  nodes: [
    {
      id: 'node-1',
      labels: ['User'],
      properties: { displayName: 'Ada Lovelace' },
    },
  ],
  rows: [
    {
      n: {
        _kind: 'node',
        id: 'node-1',
        labels: ['User'],
        properties: { displayName: 'Ada Lovelace' },
      },
    },
  ],
}

function renderWorkbench() {
  const qc = new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
      queries: { gcTime: 0, retry: false },
    },
  })
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <GraphQueryProvider>
          <GraphQueryWorkbench />
        </GraphQueryProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

describe('GraphQueryWorkbench', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('runs a query on Cmd+Enter and renders a result card with table data', async () => {
    const postSpy = vi
      .spyOn(apiClient, 'post')
      .mockResolvedValue(SAMPLE_RESULT as unknown as never)

    renderWorkbench()

    const textarea = screen.getByLabelText(
      'Cypher query',
    ) as HTMLTextAreaElement
    await userEvent.type(textarea, 'MATCH (n:User) RETURN n')
    await userEvent.keyboard('{Meta>}{Enter}{/Meta}')

    await waitFor(() => {
      expect(postSpy).toHaveBeenCalledWith(
        '/admin/graph/query',
        { query: 'MATCH (n:User) RETURN n' },
        undefined,
      )
    })

    // Footer reports the timing.
    expect(
      await screen.findByText(/Started streaming 1 record in 7 ms/),
    ).toBeInTheDocument()

    // Default tab is Table, so the cell content should render.
    expect(
      await screen.findByText(/displayName: "Ada Lovelace"/),
    ).toBeInTheDocument()

    // Card header echoes the query alongside the editor's value.
    const queryEchoes = screen.getAllByText('MATCH (n:User) RETURN n')
    expect(queryEchoes.length).toBeGreaterThanOrEqual(1)
  })

  it('renders an error card when the API rejects', async () => {
    vi.spyOn(apiClient, 'post').mockRejectedValue(
      new Error('Syntax error near MATCHX'),
    )

    renderWorkbench()

    const textarea = screen.getByLabelText('Cypher query')
    await userEvent.type(textarea, 'MATCHX (n) RETURN n')
    await userEvent.keyboard('{Meta>}{Enter}{/Meta}')

    expect(
      await screen.findByText('Syntax error near MATCHX'),
    ).toBeInTheDocument()
  })
})
