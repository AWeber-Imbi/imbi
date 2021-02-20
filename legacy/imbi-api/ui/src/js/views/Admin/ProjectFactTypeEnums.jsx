import React, { Fragment, useContext, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { FetchContext } from '../../contexts'
import { jsonSchema } from '../../schema/ProjectFactTypeEnum'

import { CRUD, Error, Loading } from '../../components'
import { displayLabelValue } from '../../utils'
import { fetchMetadata } from '../../metadata'

export function ProjectFactTypeEnums() {
  const fetchContext = useContext(FetchContext)
  const [errorMessage, setErrorMessage] = useState(null)
  const [factTypes, setFactTypes] = useState(null)
  const [projectFactTypes, setProjectFactTypes] = useState(null)
  const [projectTypes, setProjectTypes] = useState(null)
  const { t } = useTranslation()

  useEffect(() => {
    if (projectFactTypes === null) {
      fetchMetadata(
        fetchContext,
        '/project-fact-types',
        false,
        null,
        null,
        (result) => {
          setProjectFactTypes(result)
        },
        (error) => {
          setErrorMessage(error)
        }
      )
    }
  }, [projectFactTypes])

  useEffect(() => {
    if (projectTypes === null) {
      fetchMetadata(
        fetchContext,
        '/project-types',
        false,
        null,
        null,
        (result) => {
          setProjectTypes(result)
        },
        (error) => {
          setErrorMessage(error)
        }
      )
    }
  }, [projectFactTypes])

  useEffect(() => {
    if (projectTypes !== null && projectFactTypes !== null) {
      let options = []
      projectFactTypes
        .filter((factType) => factType.fact_type === 'enum')
        .map((factType) => {
          const displayValues = []
          factType.project_type_ids.map((projectTypeID) => {
            projectTypes.forEach((item) => {
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
    }
  }, [projectTypes, projectFactTypes])

  return (
    <Fragment>
      {errorMessage && <Error>{{ errorMessage }}</Error>}
      {!factTypes && (
        <div className="min-h-full flex flex-column items-center">
          <Loading className="flex-shrink" />
        </div>
      )}
      {factTypes && (
        <CRUD
          collectionIcon="fas external-link-alt"
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
                headerClassName: 'w-5/12',
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
                headerClassName: 'w-4/12'
              }
            },
            {
              title: t('common.score'),
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
      )}
    </Fragment>
  )
}
