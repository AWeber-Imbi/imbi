import React, { useContext, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { jsonSchema } from '../../schema/ProjectFactTypeEnum'

import { Context } from '../../state'
import { CRUD } from '../../components'
import { displayLabelValue } from '../../utils'

export function ProjectFactTypeEnums() {
  const [state] = useContext(Context)
  const [factTypes, setFactTypes] = useState(null)
  const { t } = useTranslation()

  useEffect(() => {
    let options = []
    state.metadata.projectFactTypes
      .filter((factType) => factType.fact_type === 'enum')
      .map((factType) => {
        const displayValues = []
        factType.project_type_ids.map((projectTypeID) => {
          state.metadata.projectTypes.forEach((item) => {
            if (item.id === projectTypeID) displayValues.push(item.name)
          })
        })
        displayValues.sort()
        const option = {
          label: factType.name + ' (' + displayValues.join(', ') + ')',
          value: factType.id
        }
        options = [...options, option]
      })
    setFactTypes(options)
  }, [state.metadata])

  return (
    <CRUD
      collectionIcon="fas list-ol"
      collectionName={t('admin.projectFactTypeEnums.collectionName')}
      collectionPath="/project-fact-type-enums"
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
          title: t('admin.projectFactTypes.itemName'),
          name: 'fact_type_id',
          type: 'select',
          castTo: 'number',
          options: factTypes,
          tableOptions: {
            className: 'truncate',
            headerClassName: 'w-6/12',
            lookupFunction: (value) => {
              return displayLabelValue(value, factTypes)
            }
          }
        },
        {
          title: t('common.icon'),
          name: 'icon_class',
          type: 'icon',
          placeholder: 'fas external-link-alt',
          default: 'fas external-link-alt',
          tableOptions: {
            className: 'text-center',
            headerClassName: 'w-1/12 text-center'
          }
        },
        {
          title: t('common.value'),
          name: 'value',
          type: 'text',
          tableOptions: {
            headerClassName: 'w-3/12'
          }
        },
        {
          title: t('terms.score'),
          name: 'score',
          type: 'number',
          minimum: 0,
          maximum: 100,
          description: t('admin.projectFactTypeEnums.scoreDescription'),
          tableOptions: {
            className: 'text-center',
            headerClassName: 'w-1/12 text-center'
          }
        }
      ]}
      errorStrings={{
        'Unique Violation': t(
          'admin.projectFactTypeEnums.errors.uniqueViolation'
        )
      }}
      itemIgnore={['created_by', 'last_modified_by']}
      itemKey="id"
      itemName={t('admin.projectFactTypeEnums.itemName')}
      itemPath="/project-fact-type-enums/{{value}}"
      itemTitle={(item) => {
        const label = displayLabelValue(item.fact_type_id, factTypes)
        return `${label} - ${item.value}`
      }}
      jsonSchema={jsonSchema}
    />
  )
}
