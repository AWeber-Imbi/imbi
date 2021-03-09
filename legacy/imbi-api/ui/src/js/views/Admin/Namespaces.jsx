import React, { useContext } from 'react'
import { useTranslation } from 'react-i18next'

import { CRUD } from '../../components'
import { asOptions, MetadataContext } from '../../metadata'
import { jsonSchema } from '../../schema/Namespace'

export function Namespaces() {
  const metadata = useContext(MetadataContext)
  const { t } = useTranslation()

  return (
    <CRUD
      collectionIcon="fas boxes"
      collectionName={t('admin.namespaces.collectionName')}
      collectionPath="/namespaces"
      columns={[
        {
          title: t('id'),
          name: 'id',
          type: 'hidden',
          omitOnAdd: true,
          tableOptions: {
            hide: true
          }
        },
        {
          title: t('common.icon'),
          name: 'icon_class',
          type: 'icon',
          placeholder: 'fas boxes',
          default: 'fas boxes',
          tableOptions: {
            className: 'text-center',
            headerClassName: 'w-1/12'
          }
        },
        {
          title: t('common.name'),
          name: 'name',
          type: 'text',
          tableOptions: {
            className: 'truncate',
            headerClassName: 'w-5/12'
          }
        },
        {
          title: t('common.slug'),
          name: 'slug',
          type: 'text',
          description: t('common.slugDescription'),
          tableOptions: {
            className: 'font-mono font-gray-500',
            headerClassName: 'w-4/12'
          }
        },
        {
          title: t('admin.namespaces.maintainedBy'),
          name: 'maintained_by',
          default: [],
          description: t('admin.namespaces.maintainedByDescription'),
          multiple: true,
          options: asOptions(metadata.groups, 'name', 'name'),
          type: 'select',
          tableOptions: {
            hide: true
          }
        }
      ]}
      errorStrings={{
        'Unique Violation': t('admin.namespaces.errors.uniqueViolation')
      }}
      itemIgnore={['created_by', 'last_modified_by']}
      itemKey="id"
      itemName={t('admin.namespaces.itemName')}
      itemPath="/namespaces/{{value}}"
      itemTitle="name"
      jsonSchema={jsonSchema}
    />
  )
}
