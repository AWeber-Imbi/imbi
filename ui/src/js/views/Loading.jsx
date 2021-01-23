import React from 'react'
import { useTranslation } from 'react-i18next'

export function Loading() {
  const { t } = useTranslation()
  return (
    <main className="flex flex-row flex-grow">
      <div className="container mx-auto my-auto max-w-xs bg-white shadow rounded-lg px-4 py-5 text-3xl text-center text-gray-500">
        <span className="pl-3">{t('common.loading')}</span>
      </div>
    </main>
  )
}
