import PropTypes from 'prop-types'
import React from 'react'
import { useTranslation } from 'react-i18next'

import { ContentArea } from '../../components'
import { User } from '../../schema'
import { setDocumentTitle } from '../../utils'

function NewEntry() {
  const { t } = useTranslation()
  setDocumentTitle(t('operationsLogNewEntry.title'))
  return (
    <ContentArea
      pageIcon="fas calendar-plus"
      pageTitle={t('operationsLogNewEntry.title')}
    />
  )
}

NewEntry.propTypes = {
  user: PropTypes.exact(User)
}

export { NewEntry }
