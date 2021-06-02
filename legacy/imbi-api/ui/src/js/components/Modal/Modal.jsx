import PropTypes from 'prop-types'
import React from 'react'

import { Backdrop } from '..'

import { Title } from './Title'
import { Body } from './Body'
import { Footer } from './Footer'

class Modal extends React.PureComponent {
  constructor(props) {
    super(props)
    this.modalRef = React.createRef()
  }

  componentDidMount() {
    this.modalRef.current.focus()
  }

  render() {
    return (
      <Backdrop>
        <span
          className="sm:align-middle sm:h-screen sm:inline-block"
          aria-hidden="true">
          &#8203;
        </span>
        <div
          className={`align-bottom sm:align-middle bg-white cursor-pointer focus:outline-none focus:ring-0 inline-block sm:max-w-2xl sm:my-8 overflow-hidden px-4 py-5 rounded-lg sm:p-6 shadow-xl text-left transform transition-all sm:w-full ${this.props.className}`}
          role="dialog"
          aria-modal="true"
          onKeyDown={(event) => {
            if (event.keyCode === 27 && this.props.onClose !== undefined)
              this.props.onClose()
          }}
          ref={this.modalRef}
          tabIndex={0}>
          {this.props.children}
        </div>
      </Backdrop>
    )
  }
}
Modal.Title = Title
Modal.Body = Body
Modal.Footer = Footer
Modal.propTypes = {
  children: PropTypes.oneOfType([
    PropTypes.array,
    PropTypes.string,
    PropTypes.element
  ]).isRequired,
  className: PropTypes.string,
  onClose: PropTypes.func
}
export { Modal }
