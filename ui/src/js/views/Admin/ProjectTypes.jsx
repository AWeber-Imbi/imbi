import React from 'react'
import { useTranslation } from 'react-i18next'

import { jsonSchema } from '../../schema/ProjectType'

import { CRUD } from '../../components'

export function ProjectTypes() {
  const { t } = useTranslation()
  return (
    <CRUD
      collectionIcon="fas cubes"
      collectionName={t('admin.projectTypes.collectionName')}
      collectionPath="/project-types"
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
          title: t('common.name'),
          name: 'name',
          type: 'text',
          tableOptions: {
            className: 'truncate',
            headerClassName: 'w-3/12'
          }
        },
        {
          title: t('common.slug'),
          name: 'slug',
          type: 'text',
          description: t('common.slugDescription'),
          tableOptions: {
            className: 'font-mono font-gray-500 truncate',
            headerClassName: 'w-2/12'
          }
        },
        {
          title: t('common.description'),
          name: 'description',
          type: 'textarea',
          tableOptions: {
            className: 'truncate',
            headerClassName: 'w-3/12'
          }
        },
        {
          title: t('common.iconClass'),
          name: 'icon_class',
          type: 'icon',
          placeholder: 'fas cubes',
          default: 'fas cubes',
          tableOptions: {
            className: 'truncate',
            headerClassName: 'w-2/12'
          }
        }
      ]}
      errorStrings={{
        'Unique Violation': t('admin.projectTypes.errors.uniqueViolation')
      }}
      itemIgnore={['created_by', 'last_modified_by']}
      itemKey="id"
      itemName={t('admin.projectTypes.itemName')}
      itemTitle="name"
      itemPath="/project-types/{{value}}"
      jsonSchema={jsonSchema}
      omitOnAdd={['id']}
    />
  )
}
