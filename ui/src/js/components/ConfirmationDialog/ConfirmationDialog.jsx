import PropTypes from 'prop-types'
import React from 'react'
import { useTranslation } from 'react-i18next'

import { Backdrop, Icon } from '..'

const icons = {
  info: 'fas info',
  warning: 'fas exclamation-triangle',
  error: 'fas exclamation',
  success: 'fas check'
}

const iconBackgroundClassName = {
  info: 'bg-blue-100 text-blue-700',
  warning: 'bg-yellow-100 text-yellow-700',
  error: 'bg-red-100 text-red-700',
  success: 'bg-green-100 text-green-700'
}

const confirmButtonClassName = {
  info: 'btn-blue',
  warning: 'btn-yellow',
  error: 'btn-red',
  success: 'btn-green'
}

function ConfirmationDialog({
  title,
  children,
  confirmationButtonText,
  mode,
  onCancel,
  onConfirm
}) {
  const { t } = useTranslation()
  return (
    <Backdrop>
      <span
        className="hidden sm:inline-block sm:align-middle sm:h-screen"
        aria-hidden="true">
        &#8203;
      </span>
      <div
        className="cursor-default inline-block align-bottom bg-white rounded-lg px-4 pt-5 pb-4 text-left overflow-hidden shadow-xl transform transition-all sm:my-8 sm:align-middle sm:max-w-lg sm:w-full sm:p-6"
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-headline">
        <div className="sm:flex sm:items-start">
          <div
            className={
              iconBackgroundClassName[mode] +
              ' mx-auto flex-shrink-0 flex items-center justify-center h-12 w-12 rounded-full sm:mx-0 sm:h-10 sm:w-10'
            }>
            <Icon icon={icons[mode]} />
          </div>
          <div className="mt-3 text-center sm:mt-0 sm:ml-4 sm:text-left">
            <h3
              className="text-lg leading-6 mt-2 font-medium text-gray-900"
              role="heading">
              {title}
            </h3>
            <div className="mt-2">{children}</div>
          </div>
        </div>
        <div className="mt-5 sm:mt-4 sm:flex sm:flex-row-reverse">
          <button
            className={confirmButtonClassName[mode]}
            onClick={(e) => {
              onConfirm(e)
            }}
            role="button"
            type="button">
            {confirmationButtonText}
          </button>
          <button
            className="btn-white mr-3"
            onClick={(e) => {
              onCancel(e)
            }}
            role="button"
            type="button">
            {t('common.cancel')}
          </button>
        </div>
      </div>
    </Backdrop>
  )
}

ConfirmationDialog.propTypes = {
  title: PropTypes.string.isRequired,
  children: PropTypes.oneOfType([
    PropTypes.arrayOf(PropTypes.element),
    PropTypes.element,
    PropTypes.string
  ]).isRequired,
  confirmationButtonText: PropTypes.string.isRequired,
  mode: PropTypes.oneOf(['info', 'warning', 'error', 'success']).isRequired,
  onCancel: PropTypes.func.isRequired,
  onConfirm: PropTypes.func.isRequired
}

export { ConfirmationDialog }
