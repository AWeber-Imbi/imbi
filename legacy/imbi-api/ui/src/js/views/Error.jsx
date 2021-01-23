import PropTypes from 'prop-types'
import React from 'react'
import { useTranslation } from 'react-i18next'

import { Error as ErrorComponent } from '../components'
import { setDocumentTitle } from '../utils'

function Error({ children }) {
  const { t } = useTranslation()
  setDocumentTitle(t('error.title'))
  return <ErrorComponent>{{ children }}</ErrorComponent>
}

Error.propTypes = {
  children: PropTypes.string.isRequired
}

export { Error }
