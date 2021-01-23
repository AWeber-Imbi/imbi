import React from 'react'
import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/extend-expect'

import { Modal } from './Modal'

describe('Modal', () => {
  it('should render the modal', () => {
    const buttonElement = (
      <div className="mockButtons">Buttons Would Be Here</div>
    )
    render(
      <div data-testid="modal">
        <Modal title="Modal Title" buttons={buttonElement}>
          Modal Content Here
        </Modal>
      </div>
    )
    const modal = screen.getByTestId('modal').children[0]
    const title = modal.getElementsByTagName('h1')[0]
    expect(title).toHaveTextContent('Modal Title')
    const button = modal.getElementsByClassName('mockButtons')[0]
    expect(button).toHaveTextContent('Buttons Would Be Here')
  })
  it('should render without buttons', () => {
    render(
      <div data-testid="modal">
        <Modal title="Modal Title">Modal Content Here</Modal>
      </div>
    )
    const modal = screen.getByTestId('modal').children[0]
    const title = modal.getElementsByTagName('h1')[0]
    expect(title).toHaveTextContent('Modal Title')
  })
})
