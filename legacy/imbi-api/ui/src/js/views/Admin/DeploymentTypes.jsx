import React from 'react'
import { useTranslation } from 'react-i18next'

import { jsonSchema } from '../../schema/DataCenter'

import { CRUD } from '../../components'

export function DeploymentTypes() {
  const { t } = useTranslation()
  return (
    <CRUD
      addPath="/admin/deployment_type"
      collectionIcon="fas upload"
      collectionName={t('admin.deploymentTypes.collectionName')}
      collectionPath="/settings/deployment_types"
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
            hide: true
          }
        },
        {
          title: t('common.iconClass'),
          name: 'icon_class',
          type: 'icon',
          placeholder: 'fas upload',
          default: 'fas upload',
          tableOptions: {
            className: 'w-min'
          }
        }
      ]}
      errorStrings={{
        'Unique Violation': t('admin.deploymentTypes.errors.uniqueViolation')
      }}
      itemKey="name"
      itemName={t('admin.deploymentTypes.itemName')}
      itemPath="/admin/deployment_type/{{value}}"
      jsonSchema={jsonSchema}
    />
  )
}
