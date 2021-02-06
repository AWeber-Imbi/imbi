import React from 'react'
import { useTranslation } from 'react-i18next'

import { jsonSchema } from '../../schema/DataCenter'

import { CRUD } from '../../components'

export function DataCenters() {
  const { t } = useTranslation()
  return (
    <CRUD
      collectionIcon="fas building"
      collectionName={t('admin.dataCenters.collectionName')}
      collectionPath="/data-centers"
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
          placeholder: 'fas building',
          default: 'fas building',
          tableOptions: {
            className: 'truncate',
            headerClassName: 'w-2/12'
          }
        }
      ]}
      errorStrings={{
        'Unique Violation': t('admin.dataCenters.errors.uniqueViolation')
      }}
      itemIgnore={['created_by', 'last_modified_by']}
      itemKey="name"
      itemName={t('admin.dataCenters.itemName')}
      itemPath="/data-centers/{{value}}"
      jsonSchema={jsonSchema}
    />
  )
}
