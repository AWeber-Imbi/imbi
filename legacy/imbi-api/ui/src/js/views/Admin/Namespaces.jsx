import React, { useContext } from 'react'
import { useTranslation } from 'react-i18next'

import { asOptions } from '../../metadata'
import { Context } from '../../state'
import { CRUD } from '../../components'
import { jsonSchema } from '../../schema/Namespace'

export function Namespaces() {
  const [state] = useContext(Context)
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
            headerClassName: 'w-4/12'
          }
        },
        {
          title: t('common.slug'),
          name: 'slug',
          type: 'text',
          description: t('common.slugDescription'),
          tableOptions: {
            className: 'font-mono font-gray-500',
            headerClassName: 'w-3/12'
          }
        },
        {
          title: t('admin.namespaces.maintainedBy.title'),
          name: 'maintained_by',
          default: [],
          description: t('admin.namespaces.maintainedBy.description'),
          multiple: true,
          options: asOptions(state.metadata.groups, 'name', 'name'),
          type: 'select',
          tableOptions: {
            hide: true
          }
        },
        {
          title: t('admin.namespaces.gitLabGroupName.title'),
          name: 'gitlab_group_name',
          description: t('admin.namespaces.gitLabGroupName.description'),
          type: 'text',
          tableOptions: {
            headerClassName: 'w-4/12'
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
