import PropTypes from 'prop-types'
import React, { Fragment } from 'react'

import { Backdrop } from '..'

function Modal({ title, children, buttons }) {
  return (
    <Backdrop>
      <Fragment>
        <span
          className="hidden sm:inline-block sm:align-middle sm:h-screen"
          aria-hidden="true">
          &#8203;
        </span>
        <div
          className="inline-block align-bottom bg-white rounded-lg px-4 py-5 text-left overflow-hidden shadow-xl transform transition-all sm:my-8 sm:align-middle sm:max-w-2xl sm:w-full sm:p-6"
          role="dialog"
          aria-modal="true"
          aria-labelledby="modal-headline">
          <h1 className="text-xl text-gray-500 border-b border-gray-400 pb-2 mb-3">
            {title}
          </h1>
          {children}
          {buttons && (
            <div className="mt-5 sm:mt-6 text-right border-t border-t-gray-400 pt-5 mt-5 space-x-3">
              {buttons}
            </div>
          )}
        </div>
      </Fragment>
    </Backdrop>
  )
}

Modal.propTypes = {
  title: PropTypes.string.isRequired,
  children: PropTypes.oneOfType([PropTypes.string, PropTypes.element])
    .isRequired,
  buttons: PropTypes.element
}

export { Modal }
