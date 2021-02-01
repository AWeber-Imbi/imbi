import React, { Fragment, useContext, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { CRUD, Error } from '../../components'
import { FetchContext } from '../../contexts'
import { fetchMetadata } from '../../metadata'
import { jsonSchema } from '../../schema/ProjectFactType'

export function ProjectFactTypes() {
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

  return (
    <Fragment>
      {errorMessage && <Error>{{ errorMessage }}</Error>}
      {!projectTypes && <div>Loading</div>}
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
              title: t('admin.projectTypes.itemName'),
              name: 'project_type_id',
              type: 'select',
              castTo: 'number',
              options: projectTypes,
              tableOptions: {
                className: 'truncate',
                headerClassName: 'w-4/12',
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
              title: t('admin.projectFactTypes.factType'),
              name: 'fact_type',
              type: 'text',
              tableOptions: {
                headerClassName: 'w-4/12'
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
                headerClassName: 'w-2/12 text-center'
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
          itemTitle="fact_type"
          jsonSchema={jsonSchema}
        />
      )}
    </Fragment>
  )
}
