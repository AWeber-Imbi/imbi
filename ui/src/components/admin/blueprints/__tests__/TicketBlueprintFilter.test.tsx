import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fireEvent, render, screen, waitFor } from '@/test/utils'

const ticketBlueprint = {
  description: null,
  enabled: true,
  filter: {
    environment: [],
    label: ['billing'],
    priority: ['urgent'],
    project_type: [],
    ticket_type: ['bug'],
  },
  json_schema: { properties: {}, type: 'object' },
  kind: 'node',
  name: 'Bug Triage',
  priority: 0,
  slug: 'bug-triage',
  type: 'Ticket',
  version: 1,
}

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  getBlueprint: vi.fn(() => Promise.resolve(ticketBlueprint)),
  listEnvironments: vi.fn(() => Promise.resolve([])),
  listProjectTypes: vi.fn(() => Promise.resolve([])),
  listTicketLabels: vi.fn(() => Promise.resolve([])),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({
    selectedOrganization: { name: 'AWeber', slug: 'aweber' },
  }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/ThemeContext', () => ({
  useTheme: () => ({ isDarkMode: false }),
}))

const { BlueprintDetail } = await import('../BlueprintDetail')
const { BlueprintFilterEditor } = await import('../BlueprintFilterEditor')
const { BlueprintForm } = await import('../BlueprintForm')
const { ImportBlueprintDialog } = await import('../ImportBlueprintDialog')

const types = ['Project', 'Ticket']

function editorProps(isTicket: boolean) {
  return {
    availableEnvironments: [],
    availableProjectTypes: [],
    envIsError: false,
    envLoading: false,
    filterEnabled: true,
    isLoading: false,
    isTicket,
    labels: [],
    orgSlug: 'aweber',
    ptIsError: false,
    ptLoading: false,
    selectedEnvironments: new Set<string>(),
    selectedPriorities: new Set<string>(),
    selectedProjectTypes: new Set<string>(),
    selectedTicketTypes: new Set<string>(),
    setFilterEnabled: vi.fn(),
    setLabels: vi.fn(),
    setSelectedEnvironments: vi.fn(),
    setSelectedPriorities: vi.fn(),
    setSelectedProjectTypes: vi.fn(),
    setSelectedTicketTypes: vi.fn(),
  }
}

describe('BlueprintFilterEditor', () => {
  it('shows the ticket pickers for a Ticket blueprint', () => {
    const props = editorProps(true)
    render(<BlueprintFilterEditor {...props} />)

    expect(screen.queryByText('Project Types')).toBeNull()
    expect(screen.queryByText('Environments')).toBeNull()
    expect(screen.getByLabelText('Labels')).toBeInTheDocument()

    fireEvent.click(screen.getByLabelText('Bug'))
    expect(props.setSelectedTicketTypes).toHaveBeenCalledWith(new Set(['bug']))
    fireEvent.click(screen.getByLabelText('Urgent'))
    expect(props.setSelectedPriorities).toHaveBeenCalledWith(
      new Set(['urgent']),
    )
  })

  it('shows the project pickers for other blueprints', () => {
    render(<BlueprintFilterEditor {...editorProps(false)} />)

    expect(screen.getByText('Project Types')).toBeInTheDocument()
    expect(screen.queryByText('Ticket Types')).toBeNull()
  })

  it('clears the ticket filter when the filter is turned off', () => {
    const props = editorProps(true)
    render(<BlueprintFilterEditor {...props} />)

    fireEvent.click(screen.getByLabelText('Enable filter'))
    expect(props.setSelectedTicketTypes).toHaveBeenCalledWith(new Set())
    expect(props.setSelectedPriorities).toHaveBeenCalledWith(new Set())
    expect(props.setLabels).toHaveBeenCalledWith([])
  })
})

describe('BlueprintForm', () => {
  beforeEach(() => vi.clearAllMocks())

  it('saves only the ticket filter fields for a Ticket blueprint', async () => {
    const onSave = vi.fn()
    render(
      <BlueprintForm
        blueprintKey={{ slug: 'bug-triage', type: 'Ticket' }}
        blueprintTypes={types}
        onCancel={vi.fn()}
        onSave={onSave}
      />,
    )

    expect(await screen.findByText('billing')).toBeInTheDocument()
    expect(screen.getByLabelText('Bug')).toBeChecked()
    fireEvent.click(screen.getByLabelText('Task'))
    fireEvent.click(screen.getByRole('button', { name: /save changes/i }))

    expect(onSave).toHaveBeenCalledTimes(1)
    expect(onSave.mock.calls[0][0].filter).toEqual({
      environment: [],
      label: ['billing'],
      priority: ['urgent'],
      project_type: [],
      ticket_type: ['bug', 'task'],
    })
  })
})

describe('BlueprintDetail', () => {
  it('shows the ticket filter', async () => {
    render(
      <BlueprintDetail
        blueprintKey={{ slug: 'bug-triage', type: 'Ticket' }}
        blueprintTypes={types}
        onBack={vi.fn()}
        onEdit={vi.fn()}
      />,
    )

    expect(await screen.findByText('Ticket Types')).toBeInTheDocument()
    expect(screen.getByText('bug')).toBeInTheDocument()
    expect(screen.getByText('Priorities')).toBeInTheDocument()
    expect(screen.getByText('urgent')).toBeInTheDocument()
    expect(screen.getByText('Labels')).toBeInTheDocument()
    expect(screen.getByText('billing')).toBeInTheDocument()
  })
})

describe('ImportBlueprintDialog', () => {
  it('shows the ticket filter in the preview', async () => {
    render(
      <ImportBlueprintDialog
        blueprintTypes={types}
        isOpen
        onClose={vi.fn()}
        onImport={vi.fn()}
      />,
    )

    fireEvent.change(screen.getByRole('textbox'), {
      target: {
        value: JSON.stringify({
          filter: { label: ['billing'], ticket_type: ['bug', 'task'] },
          json_schema: { properties: {}, type: 'object' },
          name: 'Bug Triage',
          type: 'Ticket',
        }),
      },
    })

    await waitFor(() =>
      expect(screen.getByText('1 labels, 2 ticket types')).toBeInTheDocument(),
    )
  })
})
