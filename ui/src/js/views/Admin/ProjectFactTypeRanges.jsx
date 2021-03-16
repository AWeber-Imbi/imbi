import React, { useContext, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { jsonSchema } from '../../schema/ProjectFactTypeRange'

import { Context } from '../../state'
import { CRUD } from '../../components'
import { displayLabelValue } from '../../utils'

export function ProjectFactTypeRanges() {
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
      collectionIcon="fas ruler-horizontal"
      collectionName={t('admin.projectFactTypeRanges.collectionName')}
      collectionPath="/project-fact-type-ranges"
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
            headerClassName: 'w-7/12',
            lookupFunction: (value) => {
              return displayLabelValue(value, factTypes)
            }
          }
        },
        {
          title: t('admin.projectFactTypeRanges.minValue'),
          minimum: 0,
          maximum: 100,
          name: 'min_value',
          type: 'number',
          tableOptions: {
            headerClassName: 'w-2/12 text-center',
            className: 'text-center'
          }
        },
        {
          title: t('admin.projectFactTypeRanges.maxValue'),
          name: 'max_value',
          minimum: 0,
          maximum: 100,
          type: 'number',
          tableOptions: {
            headerClassName: 'w-2/12 text-center',
            className: 'text-center'
          }
        },
        {
          title: t('terms.score'),
          name: 'score',
          type: 'number',
          minimum: 0,
          maximum: 100,
          description: t('admin.projectFactTypeRanges.scoreDescription'),
          tableOptions: {
            className: 'text-center',
            headerClassName: 'w-1/12 text-center'
          }
        }
      ]}
      errorStrings={{
        'Unique Violation': t(
          'admin.projectFactTypeRanges.errors.uniqueViolation'
        )
      }}
      itemIgnore={['created_by', 'last_modified_by']}
      itemKey="id"
      itemName={t('admin.projectFactTypeRanges.itemName')}
      itemPath="/project-fact-type-ranges/{{value}}"
      itemTitle={(item) => {
        const label = displayLabelValue(item.fact_type_id, factTypes)
        return `${label} ${item.min_value} - ${item.max_value}`
      }}
      jsonSchema={jsonSchema}
    />
  )
}
