import React, { Fragment, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { CRUD, Error } from '../../components'
import { fetchMetadata } from '../../metadata'
import { jsonSchema } from '../../schema/Namespace'

export function Namespaces() {
  const { t } = useTranslation()
  const [errorMessage, setErrorMessage] = useState(null)
  const [groups, setGroups] = useState(null)

  useEffect(() => {
    if (groups === null) {
      fetchMetadata(
        fetch,
        '/groups',
        true,
        'name',
        'name',
        (result) => {
          setGroups(result)
        },
        (error) => {
          setErrorMessage(error)
        }
      )
    }
  }, [groups])

  return (
    <Fragment>
      {errorMessage && <Error>{{ errorMessage }}</Error>}
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
            title: t('common.name'),
            name: 'name',
            type: 'text',
            tableOptions: {
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
            title: t('common.iconClass'),
            name: 'icon_class',
            type: 'icon',
            placeholder: 'fas boxes',
            default: 'fas boxes',
            tableOptions: {
              headerClassName: 'w-3/12'
            }
          },
          {
            title: t('admin.namespaces.maintainedBy'),
            name: 'maintained_by',
            default: [],
            description: t('admin.namespaces.maintainedByDescription'),
            multiple: true,
            options: groups,
            type: 'select',
            tableOptions: {
              hide: true
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
    </Fragment>
  )
}
