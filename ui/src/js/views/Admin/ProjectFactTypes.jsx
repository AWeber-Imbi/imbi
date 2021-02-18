import React, { Fragment, useContext, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { CRUD, Error, Loading } from '../../components'
import { FetchContext } from '../../contexts'
import { fetchMetadata } from '../../metadata'
import { jsonSchema } from '../../schema/ProjectFactType'

function displayLabelValue(value, options, defaultValue = null) {
  let displayValue = defaultValue
  options.forEach((item) => {
    if (item.value === value) displayValue = item.label
  })
  return displayValue
}

export function ProjectFactTypes() {
  const fetch = useContext(FetchContext)
  const [errorMessage, setErrorMessage] = useState(null)
  const [projectTypes, setProjectTypes] = useState(null)
  const { t } = useTranslation()

  const dataTypeOptions = [
    { label: 'Boolean', value: 'boolean' },
    { label: 'ISO-8601 Date', value: 'date' },
    { label: 'Decimal', value: 'decimal' },
    { label: 'Integer', value: 'integer' },
    { label: 'String', value: 'string' },
    { label: 'ISO-8601 Timestamp', value: 'timestamp' }
  ]

  const factTypeOptions = [
    { label: 'Enum', value: 'enum' },
    { label: 'Free-Form', value: 'free-form' },
    { label: 'Range', value: 'range' }
  ]

  useEffect(() => {
    if (projectTypes === null) {
      fetchMetadata(
        fetch,
        '/project-types',
        true,
        'name',
        'id',
        (result) => {
          setProjectTypes(result)
        },
        (error) => {
          setErrorMessage(error)
        }
      )
    }
  }, [projectTypes])

  return (
    <Fragment>
      {errorMessage && <Error>{{ errorMessage }}</Error>}
      {!projectTypes && (
        <div className="min-h-full flex flex-column items-center">
          <Loading className="flex-shrink" />
        </div>
      )}
      {projectTypes && (
        <CRUD
          collectionIcon="fas ruler"
          collectionName={t('admin.projectFactTypes.collectionName')}
          collectionPath="/project-fact-types"
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
              title: t('admin.projectTypes.itemName'),
              name: 'project_type_ids',
              type: 'select',
              castTo: 'number',
              options: projectTypes,
              multiple: true,
              tableOptions: {
                className: 'truncate',
                headerClassName: 'w-5/12',
                lookupFunction: (value) => {
                  const displayValues = []
                  value.map((projectTypeID) => {
                    projectTypes.forEach((item) => {
                      if (item.value === projectTypeID)
                        displayValues.push(item.label)
                    })
                  })
                  displayValues.sort()
                  return displayValues.join(', ')
                }
              }
            },
            {
              title: t('admin.projectFactTypes.dataType'),
              name: 'data_type',
              type: 'select',
              options: dataTypeOptions,
              tableOptions: {
                className: 'text-center truncate',
                headerClassName: 'text-center w-1/12',
                lookupFunction: (value) => {
                  return displayLabelValue(value, dataTypeOptions)
                }
              }
            },
            {
              title: t('admin.projectFactTypes.factType'),
              name: 'fact_type',
              type: 'select',
              options: factTypeOptions,
              tableOptions: {
                className: 'text-center truncate',
                headerClassName: 'text-center w-1/12',
                lookupFunction: (value) => {
                  return displayLabelValue(value, factTypeOptions)
                }
              }
            },
            {
              title: t('admin.projectFactTypes.uiOptions'),
              name: 'ui_options',
              type: 'select',
              default: [],
              options: [
                { label: 'Display as Badge', value: 'display-as-badge' },
                { label: 'Hidden', value: 'hidden' }
              ],
              multiple: true,
              tableOptions: {
                hide: true
              }
            },
            {
              title: t('common.description'),
              name: 'description',
              type: 'textarea',
              tableOptions: {
                hide: true
              }
            },
            {
              title: t('admin.projectFactTypes.weight'),
              name: 'weight',
              type: 'number',
              minimum: 0,
              maximum: 100,
              description: t('admin.projectFactTypes.weightDescription'),
              tableOptions: {
                className: 'text-center',
                headerClassName: 'w-1/12 text-center'
              }
            }
          ]}
          errorStrings={{
            'Unique Violation': t(
              'admin.projectFactTypes.errors.uniqueViolation'
            )
          }}
          itemIgnore={['created_by', 'last_modified_by']}
          itemKey="id"
          itemName={t('admin.projectFactTypes.itemName')}
          itemPath="/project-fact-types/{{value}}"
          itemTitle="name"
          jsonSchema={jsonSchema}
        />
      )}
    </Fragment>
  )
}
