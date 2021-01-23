import PropTypes from 'prop-types'
import React from 'react'
import { useTranslation } from 'react-i18next'

import { ContentArea } from '../../components'
import { User } from '../../schema'

function OperationsLog() {
  const { t } = useTranslation()
  return (
    <ContentArea
      buttonTitle={t('operationsLog.addEntry')}
      pageIcon="fas clipboard"
      pageTitle={t('operationsLog.title')}
    />
  )
}

OperationsLog.propTypes = {
  user: PropTypes.exact(User)
}

export { OperationsLog }
