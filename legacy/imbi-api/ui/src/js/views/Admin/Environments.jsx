import React from 'react'
import { useTranslation } from 'react-i18next'

import { jsonSchema } from '../../schema/Environments'

import { CRUD } from '../../components'

export function Environments() {
  const { t } = useTranslation()
  return (
    <CRUD
      collectionIcon="fas tree"
      collectionName={t('admin.environments.collectionName')}
      collectionPath="/environments"
      columns={[
        {
          title: t('common.name'),
          name: 'name',
          type: 'text',
          tableOptions: {
            headerClassName: 'w-3/12'
          }
        },
        {
          title: t('common.description'),
          name: 'description',
          type: 'textarea',
          tableOptions: {
            className: 'truncate',
            headerClassName: 'w-4/12'
          }
        },
        {
          title: t('common.iconClass'),
          name: 'icon_class',
          type: 'icon',
          placeholder: 'fas tree',
          default: 'fas tree',
          tableOptions: {
            headerClassName: 'w-3/12'
          }
        }
      ]}
      errorStrings={{
        'Unique Violation': t('admin.projectTypes.errors.uniqueViolation')
      }}
      itemIgnore={['created_by', 'last_modified_by']}
      itemKey="name"
      itemName={t('admin.environments.itemName')}
      itemPath="/environments/{{value}}"
      jsonSchema={jsonSchema}
    />
  )
}
