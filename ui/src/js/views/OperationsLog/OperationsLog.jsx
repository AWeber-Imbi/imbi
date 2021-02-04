import PropTypes from 'prop-types'
import React from 'react'
import { useTranslation } from 'react-i18next'

import { ContentArea } from '../../components'
import { User } from '../../schema'
import { setDocumentTitle } from '../../utils'

function OperationsLog() {
  const { t } = useTranslation()
  setDocumentTitle(t('operationsLog.title'))
  return (
    <ContentArea
      buttonDestination="/ui/operations-log/new"
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
