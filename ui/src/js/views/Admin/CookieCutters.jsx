import React, { Fragment, useContext, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { CRUD, Error } from '../../components'
import { FetchContext } from '../../contexts'
import { fetchMetadata } from '../../metadata'
import { jsonSchema } from '../../schema/CookieCutter'

export function CookieCutters() {
  const fetch = useContext(FetchContext)
  const [errorMessage, setErrorMessage] = useState(null)
  const [projectTypes, setProjectTypes] = useState(null)
  const { t } = useTranslation()

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

  const options = [
    { label: 'Dashboard', value: 'dashboard' },
    { label: 'Project', value: 'project' }
  ]

  return (
    <Fragment>
      {errorMessage && <Error>{{ errorMessage }}</Error>}
      {!projectTypes && <div>Loading</div>}
      {projectTypes && (
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
                headerClassName: 'w-3/12'
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
              options: projectTypes,
              tableOptions: {
                className: 'truncate',
                headerClassName: 'w-2/12',
                lookupFunction: (value) => {
                  let displayValue = null
                  projectTypes.forEach((item) => {
                    if (item.value === value) displayValue = item.label
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
                headerClassName: 'w-3/12'
              }
            },
            {
              title: t('admin.cookieCutters.url'),
              name: 'url',
              description: t('admin.cookieCutters.urlDescription'),
              type: 'text',
              tableOptions: {
                className: 'truncate',
                headerClassName: 'w-2/12'
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
      )}
    </Fragment>
  )
}
