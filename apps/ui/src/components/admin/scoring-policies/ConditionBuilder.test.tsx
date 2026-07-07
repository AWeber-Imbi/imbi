import { describe, expect, it, vi } from 'vitest'

import { fireEvent, render, screen } from '@/test/utils'
import type { Condition } from '@/types'

import {
  ConditionBuilder,
  conditionToEnglish,
  DEFAULT_CONDITION,
  normalizeCondition,
} from './ConditionBuilder'

describe('normalizeCondition', () => {
  it('strips null siblings the API includes on each node', () => {
    const raw = {
      all: null,
      any: null,
      attribute: 'deprecated',
      not: null,
      op: 'eq',
      relationship: null,
      value: true,
    } as unknown as Condition

    expect(normalizeCondition(raw)).toEqual({
      attribute: 'deprecated',
      op: 'eq',
      value: true,
    })
  })

  it('recurses through relationship and combinator nodes', () => {
    const raw = {
      relationship: {
        direction: 'outgoing',
        edge: 'DEPENDS_ON',
        quantifier: 'none',
        where: {
          all: null,
          any: null,
          attribute: 'deprecated',
          not: null,
          op: 'eq',
          relationship: null,
          value: true,
        },
      },
    } as unknown as Condition

    expect(normalizeCondition(raw)).toEqual(DEFAULT_CONDITION)
  })

  it('drops the value key for present/absent ops', () => {
    const raw = { attribute: 'description', op: 'present' } as Condition
    expect(normalizeCondition(raw)).toEqual({
      attribute: 'description',
      op: 'present',
    })
  })
})

describe('conditionToEnglish', () => {
  it('describes the deprecation-contagion default', () => {
    expect(conditionToEnglish(DEFAULT_CONDITION)).toBe(
      'no outgoing dependency where deprecated is true',
    )
  })

  it('describes a compound all/any tree', () => {
    const cond: Condition = {
      all: [
        { attribute: 'deprecated', op: 'eq', value: true },
        { attribute: 'tier', op: 'eq', value: 'critical' },
      ],
    }
    expect(conditionToEnglish(cond)).toBe(
      '(deprecated is true AND tier is "critical")',
    )
  })
})

describe('ConditionBuilder', () => {
  const renderBuilder = (value: Condition, onChange = vi.fn()) => {
    render(
      <ConditionBuilder
        falseScore={0}
        onChange={onChange}
        trueScore={100}
        value={value}
        weight={15}
      />,
    )
    return onChange
  }

  it('renders the English preview of the tree', () => {
    renderBuilder(DEFAULT_CONDITION)
    expect(
      screen.getByText('no outgoing dependency where deprecated is true'),
    ).toBeInTheDocument()
  })

  it('edits an attribute leaf and emits the updated tree', () => {
    const onChange = renderBuilder({
      attribute: 'deprecated',
      op: 'eq',
      value: true,
    })
    const input = screen.getByPlaceholderText('attribute')
    fireEvent.change(input, { target: { value: 'archived' } })
    expect(onChange).toHaveBeenCalledWith({
      attribute: 'archived',
      op: 'eq',
      value: true,
    })
  })

  it('round-trips a tree edited as JSON', () => {
    const onChange = renderBuilder({
      attribute: 'deprecated',
      op: 'eq',
      value: true,
    })
    fireEvent.click(screen.getByText('JSON'))
    const next: Condition = { attribute: 'tier', op: 'eq', value: 'critical' }
    const textarea = screen.getByRole('textbox')
    fireEvent.change(textarea, {
      target: { value: JSON.stringify(next) },
    })
    expect(onChange).toHaveBeenCalledWith(next)
    expect(screen.getByText('Valid condition tree')).toBeInTheDocument()
  })
})
