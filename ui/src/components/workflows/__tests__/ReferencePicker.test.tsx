import { describe, expect, it, vi } from 'vitest'

import { fireEvent, render, screen, waitFor } from '@/test/utils'

import { TemplateInput } from '../ReferencePicker'
import type { ReferenceGroup } from '../references'

const GROUPS: ReferenceGroup[] = [
  {
    key: 'triage',
    mayNotRun: true,
    references: [{ path: 'triage.result.risk', type: 'string' }],
    title: 'Triage',
  },
  {
    key: 'trigger',
    mayNotRun: false,
    references: [{ path: 'trigger.service', type: 'string' }],
    title: 'Trigger',
  },
]

function renderInput(value: string, groups = GROUPS) {
  const onChange = vi.fn()
  render(
    <TemplateInput
      groups={groups}
      id="prompt"
      multiline={false}
      onChange={onChange}
      value={value}
    />,
  )
  return onChange
}

describe('TemplateInput', () => {
  it('lists references by step and appends the one picked', async () => {
    const onChange = renderInput('Risk: ')
    fireEvent.click(screen.getByRole('button', { name: 'Insert a reference' }))
    expect(await screen.findByText('Triage')).toBeInTheDocument()
    expect(screen.getByText('may not run')).toBeInTheDocument()
    expect(screen.getByText('Trigger')).toBeInTheDocument()
    fireEvent.click(screen.getByText('triage.result.risk'))
    expect(onChange).toHaveBeenCalledWith('Risk: {{ triage.result.risk }}')
  })

  it('finds references by the title of their step', async () => {
    renderInput('', [{ ...GROUPS[0], title: 'Security review' }, GROUPS[1]])
    fireEvent.click(screen.getByRole('button', { name: 'Insert a reference' }))
    fireEvent.change(await screen.findByPlaceholderText('Search references…'), {
      target: { value: 'security' },
    })
    expect(await screen.findByText('triage.result.risk')).toBeInTheDocument()
    expect(screen.queryByText('trigger.service')).not.toBeInTheDocument()
  })

  it('inserts at the caret', async () => {
    const onChange = renderInput('Hello world')
    const input = screen.getByRole('textbox')
    ;(input as HTMLInputElement).setSelectionRange(6, 6)
    fireEvent.select(input)
    fireEvent.click(screen.getByRole('button', { name: 'Insert a reference' }))
    fireEvent.click(await screen.findByText('trigger.service'))
    expect(onChange).toHaveBeenCalledWith('Hello {{ trigger.service }}world')
  })

  it('returns focus to the field after the pick', async () => {
    renderInput('Risk: ')
    fireEvent.click(screen.getByRole('button', { name: 'Insert a reference' }))
    fireEvent.click(await screen.findByText('trigger.service'))
    await waitFor(() => expect(screen.getByRole('textbox')).toHaveFocus())
  })

  it('has no picker when nothing comes before the step', () => {
    renderInput('', [])
    expect(
      screen.queryByRole('button', { name: 'Insert a reference' }),
    ).not.toBeInTheDocument()
  })
})
