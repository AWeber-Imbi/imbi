import React from 'react'
import { useTranslation } from 'react-i18next'

import { jsonSchema } from '../../schema/ProjectLinkType'

import { CRUD } from '../../components'

export function ProjectLinkTypes() {
  const { t } = useTranslation()
  return (
    <CRUD
      collectionIcon="fas external-link-alt"
      collectionName={t('admin.projectLinkTypes.collectionName')}
      collectionPath="/project-link-types"
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
          title: t('admin.projectLinkTypes.linkType'),
          name: 'link_type',
          type: 'text',
          tableOptions: {
            headerClassName: 'w-5/12'
          }
        },
        {
          title: t('common.iconClass'),
          name: 'icon_class',
          type: 'icon',
          placeholder: 'fas external-link-alt',
          default: 'fas external-link-alt',
          tableOptions: {
            headerClassName: 'w-5/12'
          }
        }
      ]}
      errorStrings={{
        'Unique Violation': t('admin.projectLinkTypes.errors.uniqueViolation')
      }}
      itemIgnore={['created_by', 'last_modified_by']}
      itemKey="id"
      itemName={t('admin.projectLinkTypes.itemName')}
      itemPath="/project-link-types/{{value}}"
      itemTitle="link_type"
      jsonSchema={jsonSchema}
    />
  )
}
