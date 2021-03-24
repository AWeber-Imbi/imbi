import PropTypes from 'prop-types'
import React from 'react'
import { useTranslation } from 'react-i18next'

import Logo from '../../../images/logo.svg'

function Loading({ caption, className }) {
  const { t } = useTranslation()
  return (
    <div
      className={`container font-sans font-normal mx-auto my-auto max-w-xs px-4 py-5 text-3xl text-center text-gray-500 ${className}`}>
      <img
        className="animate-bounce inline-block mr-3"
        style={{ height: '56px', width: '56px' }}
        src={Logo}
        alt=""
      />
      {t(caption)}
    </div>
  )
}
Loading.defaultProps = {
  caption: 'common.loading',
  className: ''
}

Loading.propTypes = {
  caption: PropTypes.string,
  className: PropTypes.string
}

export { Loading }
