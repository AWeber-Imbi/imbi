import React from 'react'
import { useTranslation } from 'react-i18next'

import { jsonSchema } from '../../schema/DataCenter'

import { CRUD } from '../../components'

export function DataCenters() {
  const { t } = useTranslation()
  return (
    <CRUD
      addPath="/admin/data_center"
      collectionIcon="fas building"
      collectionName={t('admin.dataCenters.collectionName')}
      collectionPath="/settings/data_centers"
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
          placeholder: 'fas building',
          default: 'fas building',
          tableOptions: {
            headerClassName: 'w-2/12'
          }
        }
      ]}
      errorStrings={{
        'Unique Violation': t('admin.dataCenters.errors.uniqueViolation')
      }}
      itemKey="name"
      itemName={t('admin.dataCenters.itemName')}
      itemPath="/admin/data_center/{{value}}"
      jsonSchema={jsonSchema}
    />
  )
}
