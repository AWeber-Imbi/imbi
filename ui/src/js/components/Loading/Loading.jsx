import PropTypes from 'prop-types'
import React from 'react'
import { useTranslation } from 'react-i18next'

import Logo from '../../../images/logo.svg'

function Loading({ caption }) {
  const { t } = useTranslation()
  return (
    <div className="container mx-auto my-auto max-w-xs px-4 py-5 text-3xl text-center text-gray-500">
      <img
        className="animate-bounce inline-block mr-2"
        style={{ height: '3rem', width: '3rem' }}
        src={Logo}
        alt=""
      />
      {t(caption)}
    </div>
  )
}
Loading.defaultProps = {
  caption: 'common.loading'
}

Loading.propTypes = {
  caption: PropTypes.string
}

export { Loading }
