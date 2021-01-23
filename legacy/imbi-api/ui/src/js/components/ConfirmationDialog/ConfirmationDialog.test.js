import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/extend-expect'

import '../../icons'
import '../../i18n'

import { ConfirmationDialog } from './ConfirmationDialog'

describe('Alert', () => {
  it('should render an alert with info attributes', () => {
    const mockOnCancel = jest.fn()
    const mockOnConfirm = jest.fn()

    render(
      <div data-testid="confirmation">
        <ConfirmationDialog
          mode="error"
          onCancel={mockOnCancel}
          onConfirm={mockOnConfirm}
          title="Are You Sure?"
          confirmationButtonText="Let's do it!">
          There is no turning back!
        </ConfirmationDialog>
      </div>
    )
    const dialog = screen.getByTestId('confirmation').children[0]

    const title = dialog.getElementsByTagName('h3')[0]
    expect(title).toHaveTextContent('Are You Sure?')

    const svg = dialog.getElementsByTagName('svg')[0]
    expect(svg.dataset.prefix).toBe('fas')
    expect(svg.dataset.icon).toBe('exclamation')

    const buttons = screen.getAllByRole('button')

    expect(buttons[0]).toHaveTextContent("Let's do it!")
    fireEvent.click(buttons[0])
    expect(mockOnConfirm.mock.calls.length).toBe(1)

    expect(buttons[1]).toHaveTextContent('Cancel')
    fireEvent.click(buttons[1])
    expect(mockOnCancel.mock.calls.length).toBe(1)
  })
})
