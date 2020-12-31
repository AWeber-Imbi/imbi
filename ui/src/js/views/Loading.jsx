import React from 'react'
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faSpinner } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'

export function Loading() {
  const { t } = useTranslation()
  return (
    <main className="content-between align-middle">
      <div className="text-3xl text-center text-gray-500 block">
        <FontAwesomeIcon icon={faSpinner} spin />
        <span className="pl-4 text-italic">{t('common.loading')}</span>
      </div>
    </main>
  )
}
