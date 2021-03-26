import PropTypes from 'prop-types'
import React from 'react'
import { useTranslation } from 'react-i18next'

import { Icon } from '..'

function Error({ children, className }) {
  const { t } = useTranslation()
  return (
    <div
      className={`container font-normal font-sans mx-auto my-auto max-w-2xl bg-red-50 shadow rounded-lg p-5 text-base text-red-700 ${
        className !== undefined ? className : ''
      }`}>
      <Icon icon="fas exclamation-circle" />
      <span className="pl-1">
        <span className="font-bold">{t('error.title')}:</span> {children}
      </span>
    </div>
  )
}
Error.propTypes = {
  children: PropTypes.oneOfType([
    PropTypes.arrayOf(PropTypes.element),
    PropTypes.element,
    PropTypes.string
  ]).isRequired,
  className: PropTypes.string
}
export { Error }
