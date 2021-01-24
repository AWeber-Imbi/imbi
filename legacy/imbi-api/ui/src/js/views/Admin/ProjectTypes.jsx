import React from 'react'
import { useTranslation } from 'react-i18next'

import { jsonSchema } from '../../schema/ProjectType'

import { CRUD } from '../../components'

export function ProjectTypes() {
  const { t } = useTranslation()
  return (
    <CRUD
      addPath="/admin/project_type"
      collectionIcon="fas cubes"
      collectionName={t('admin.projectTypes.collectionName')}
      collectionPath="/settings/project_types"
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
          title: t('common.slug'),
          name: 'slug',
          type: 'text',
          description: t('common.slugDescription'),
          tableOptions: {
            className: 'font-mono font-gray-500',
            headerClassName: 'w-2/12'
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
          placeholder: 'fas cubes',
          default: 'fas cubes',
          tableOptions: {
            headerClassName: 'w-2/12'
          }
        }
      ]}
      errorStrings={{
        'Unique Violation': t('admin.projectTypes.errors.uniqueViolation')
      }}
      itemKey="name"
      itemName={t('admin.projectTypes.itemName')}
      itemPath="/admin/project_type/{{value}}"
      jsonSchema={jsonSchema}
    />
  )
}
