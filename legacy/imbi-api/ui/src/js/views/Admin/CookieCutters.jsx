import React, { useContext } from 'react'
import { useTranslation } from 'react-i18next'

import { asOptions } from '../../metadata'
import { Context } from '../../state'
import { CRUD } from '../../components'
import { jsonSchema } from '../../schema/CookieCutter'

export function CookieCutters() {
  const [state] = useContext(Context)
  const { t } = useTranslation()

  const options = [
    { label: 'Dashboard', value: 'dashboard' },
    { label: 'Project', value: 'project' }
  ]

  return (
    <CRUD
      collectionIcon="fas cookie"
      collectionName={t('admin.cookieCutters.collectionName')}
      collectionPath="/cookie-cutters"
      columns={[
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
          title: t('admin.cookieCutters.type'),
          name: 'type',
          type: 'select',
          options: options,
          tableOptions: {
            headerClassName: 'w-1/12',
            lookupFunction: (value) => {
              let displayValue = null
              options.forEach((item) => {
                if (item.value === value) displayValue = item.label
              })
              return displayValue
            }
          }
        },
        {
          title: t('admin.projectTypes.itemName'),
          name: 'project_type_id',
          type: 'select',
          castTo: 'number',
          options: asOptions(state.metadata.projectTypes),
          tableOptions: {
            className: 'truncate',
            headerClassName: 'w-2/12',
            lookupFunction: (value) => {
              let displayValue = null
              state.metadata.projectTypes.forEach((item) => {
                if (item.id === value) displayValue = item.name
              })
              return displayValue
            }
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
          title: t('admin.cookieCutters.url'),
          name: 'url',
          description: t('admin.cookieCutters.urlDescription'),
          type: 'text',
          tableOptions: {
            hide: true
          }
        }
      ]}
      errorStrings={{
        'Unique Violation': t('admin.cookieCutters.errors.uniqueViolation')
      }}
      itemIgnore={['created_by', 'last_modified_by']}
      itemKey="name"
      itemName={t('admin.cookieCutters.itemName')}
      itemPath="/cookie-cutters/{{value}}"
      jsonSchema={jsonSchema}
    />
  )
}
