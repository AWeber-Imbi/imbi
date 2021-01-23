import React from 'react'
import { useTranslation } from 'react-i18next'

import { Error } from '.'

export function NotFound() {
  const { t } = useTranslation()
  return <Error>{t('error.notFound')}</Error>
}
