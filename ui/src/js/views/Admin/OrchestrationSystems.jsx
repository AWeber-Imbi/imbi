import React from 'react'
import { useTranslation } from 'react-i18next'

import { jsonSchema } from '../../schema/OrchestrationSystem'

import { CRUD } from '../../components'

export function OrchestrationSystems() {
  const { t } = useTranslation()
  return (
    <CRUD
      addPath="/admin/orchestration_system"
      collectionIcon="fas cogs"
      collectionName={t('admin.orchestrationSystems.collectionName')}
      collectionPath="/settings/orchestration_systems"
      columns={[
        {
          title: t('common.name'),
          name: 'name',
          type: 'text',
          tableOptions: {
            className: 'min-w-sm'
          }
        },
        {
          title: t('common.description'),
          name: 'description',
          type: 'textarea',
          tableOptions: {
            className: 'max-w-lg truncate'
          }
        },
        {
          title: t('common.iconClass'),
          name: 'icon_class',
          type: 'icon',
          placeholder: 'fas cogs',
          default: 'fas cogs',
          tableOptions: {
            className: 'w-min'
          }
        }
      ]}
      errorStrings={{
        'Unique Violation': t(
          'admin.orchestrationSystems.errors.uniqueViolation'
        )
      }}
      itemKey="name"
      itemName={t('admin.orchestrationSystems.itemName')}
      itemPath="/admin/orchestration_system/{{value}}"
      jsonSchema={jsonSchema}
    />
  )
}
