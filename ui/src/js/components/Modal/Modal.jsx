import PropTypes from 'prop-types'
import React from 'react'

function Modal({ title, children, buttons }) {
  return (
    <div className="fixed z-10 inset-0 overflow-y-auto">
      <div className="flex items-end justify-center min-h-screen pt-4 px-4 pb-20 text-center sm:block sm:p-0">
        <div className="fixed inset-0 transition-opacity" aria-hidden="true">
          <div className="absolute inset-0 bg-gray-500 opacity-75" />
        </div>
        <span
          className="hidden sm:inline-block sm:align-middle sm:h-screen"
          aria-hidden="true">
          &#8203;
        </span>
        <div
          className="inline-block align-bottom bg-white rounded-lg px-4 pt-5 pb-4 text-left overflow-hidden shadow-xl transform transition-all sm:my-8 sm:align-middle sm:max-w-2xl sm:w-full sm:p-6"
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
      </div>
    </div>
  )
}

Modal.propTypes = {
  title: PropTypes.string.isRequired,
  children: PropTypes.oneOfType([PropTypes.string, PropTypes.element])
    .isRequired,
  buttons: PropTypes.element
}

export { Modal }
