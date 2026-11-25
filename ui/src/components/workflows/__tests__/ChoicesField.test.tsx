import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { fireEvent, render, screen, waitFor } from '@/test/utils'

import { ParamsForm } from '../ParamsForm'
import type { ParamField } from '../schemaFields'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  listIntegrations: vi.fn(),
  listWorkflowStepChoices: vi.fn(),
}))

const FIELD: ParamField = {
  dependsOn: ['region'],
  kind: 'choices',
  label: 'Datasource',
  multiple: false,
  name: 'datasource',
  required: true,
  step: 'grafana.gather_metrics',
}

function renderChoices(
  params: Record<string, unknown>,
  field: ParamField = FIELD,
) {
  const onChange = vi.fn()
  render(
    <ParamsForm
      fields={[field]}
      idPrefix="node"
      onChange={onChange}
      onRemoveItem={vi.fn()}
      orgSlug="acme"
      params={params}
      references={[]}
      webhookProject={false}
    />,
  )
  return onChange
}

describe('ParamsForm choices', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.listWorkflowStepChoices).mockResolvedValue([
      { label: 'Prometheus', value: 'prom' },
    ])
  })

  it('loads choices with the values the field depends on', async () => {
    const onChange = renderChoices({
      integration: 'grafana-prod',
      query: 'up',
      region: 'us',
    })

    fireEvent.click(await screen.findByText('Choose or type…'))
    fireEvent.click(await screen.findByRole('option', { name: /Prometheus/ }))

    expect(endpoints.listWorkflowStepChoices).toHaveBeenCalledWith(
      'acme',
      'grafana-prod',
      'grafana.gather_metrics',
      { field: 'datasource', params: { region: 'us' } },
      expect.anything(),
    )
    expect(onChange).toHaveBeenCalledWith('datasource', 'prom')
  })

  it('skips the lookup without an integration or with a template', async () => {
    renderChoices({ integration: '', region: 'us' })
    renderChoices({ integration: 'grafana-prod', region: '{{ trigger.r }}' })

    await screen.findAllByText('Choose or type…')
    expect(endpoints.listWorkflowStepChoices).not.toHaveBeenCalled()
  })

  it('takes free text', async () => {
    const onChange = renderChoices({ integration: '' })

    fireEvent.click(await screen.findByText('Choose or type…'))
    fireEvent.change(screen.getByPlaceholderText('Search...'), {
      target: { value: '{{ trigger.ds }}' },
    })
    fireEvent.click(await screen.findByRole('option', { name: /Use/ }))

    expect(onChange).toHaveBeenCalledWith('datasource', '{{ trigger.ds }}')
  })

  it('says when the choices fail to load', async () => {
    vi.mocked(endpoints.listWorkflowStepChoices).mockRejectedValue(
      new Error('502'),
    )
    renderChoices({ integration: 'grafana-prod' })

    expect(
      await screen.findByText('Could not load the choices. Type a value.'),
    ).toBeVisible()
  })

  it('adds and removes values of a list field', async () => {
    const onChange = renderChoices(
      { integration: 'grafana-prod', labels: ['prom', 'other'] },
      { ...FIELD, dependsOn: [], multiple: true, name: 'labels' },
    )

    expect(await screen.findByText('Prometheus')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Remove other' }))

    expect(onChange).toHaveBeenCalledWith('labels', ['prom'])
    await waitFor(() =>
      expect(endpoints.listWorkflowStepChoices).toHaveBeenCalledTimes(1),
    )
  })

  it('offers the integrations of the plugin with workflow steps on', async () => {
    const steps = { 'workflow-steps': { enabled: true, options: {} } }
    vi.mocked(endpoints.listIntegrations).mockResolvedValue([
      { capabilities: steps, name: 'Grafana', plugin: 'grafana', slug: 'g' },
      { capabilities: {}, name: 'Off', plugin: 'grafana', slug: 'off' },
      { capabilities: steps, name: 'Other', plugin: 'other', slug: 'o' },
      {
        capabilities: steps,
        name: 'Inactive',
        plugin: 'grafana',
        slug: 'i',
        status: 'inactive',
      },
    ] as unknown as Awaited<ReturnType<typeof endpoints.listIntegrations>>)
    renderChoices(
      {},
      {
        kind: 'source',
        label: 'Integration',
        name: 'integration',
        plugin: 'grafana',
        required: true,
        source: 'integration',
      },
    )

    fireEvent.click(await screen.findByText('Choose…'))

    expect(await screen.findByRole('option', { name: 'Grafana' })).toBeVisible()
    expect(screen.getAllByRole('option')).toHaveLength(1)
  })
})
