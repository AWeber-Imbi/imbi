import React from 'react'
import { useTranslation } from 'react-i18next'

import { jsonSchema } from '../../schema/DataCenter'

import { CRUD } from '../../components'

export function DeploymentTypes() {
  const { t } = useTranslation()
  return (
    <CRUD
      collectionIcon="fas upload"
      collectionName={t('admin.deploymentTypes.collectionName')}
      collectionPath="/deployment-types"
      columns={[
        {
          title: t('common.name'),
          name: 'name',
          type: 'text',
          tableOptions: {
            className: 'truncate',
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
          placeholder: 'fas upload',
          default: 'fas upload',
          tableOptions: {
            className: 'truncate',
            headerClassName: 'w-2/12'
          }
        }
      ]}
      errorStrings={{
        'Unique Violation': t('admin.deploymentTypes.errors.uniqueViolation')
      }}
      itemIgnore={['created_by', 'last_modified_by']}
      itemKey="name"
      itemName={t('admin.deploymentTypes.itemName')}
      itemPath="/deployment-types/{{value}}"
      jsonSchema={jsonSchema}
    />
  )
}
