import React from 'react'
import { useTranslation } from 'react-i18next'

import { ContentArea } from '../components/'
import { setDocumentTitle } from '../utils'

export function Dashboard() {
  const { t } = useTranslation()
  setDocumentTitle(t('headerNavItems.dashboard'))
  return (
    <ContentArea pageIcon="fas chart-line" pageTitle={t('common.welcome')} />
  )
}
