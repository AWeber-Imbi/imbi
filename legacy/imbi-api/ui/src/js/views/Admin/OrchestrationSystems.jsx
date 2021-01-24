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
            headerClassName: 'w-2/12'
          }
        },
        {
          title: t('common.description'),
          name: 'description',
          type: 'textarea',
          tableOptions: {
            className: 'truncate',
            headerClassName: 'w-6/12'
          }
        },
        {
          title: t('common.iconClass'),
          name: 'icon_class',
          type: 'icon',
          placeholder: 'fas cogs',
          default: 'fas cogs',
          tableOptions: {
            headerClassName: 'w-2/12'
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
