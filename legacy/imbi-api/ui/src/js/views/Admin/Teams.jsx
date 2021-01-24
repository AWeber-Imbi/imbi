import React, { Fragment, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { CRUD, Error } from '../../components'
import { fetchGroups } from '../../settings'
import { jsonSchema } from '../../schema/Team'

export function Teams() {
  const { t } = useTranslation()
  const [errorMessage, setErrorMessage] = useState(null)
  const [groups, setGroups] = useState(null)

  useEffect(() => {
    if (groups === null) {
      fetchGroups(
        fetch,
        true,
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
        addPath="/admin/team"
        collectionIcon="fas users"
        collectionName={t('admin.teams.collectionName')}
        collectionPath="/settings/teams"
        columns={[
          {
            title: t('common.name'),
            name: 'name',
            type: 'text',
            tableOptions: {
              headerClassName: 'w-3/12'
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
            placeholder: 'fas users',
            default: 'fas users',
            tableOptions: {
              headerClassName: 'w-2/12'
            }
          },
          {
            title: t('common.group'),
            name: 'group',
            options: groups,
            type: 'select',
            tableOptions: {
              headerClassName: 'w-2/12'
            }
          }
        ]}
        errorStrings={{
          'Unique Violation': t('admin.teams.errors.uniqueViolation')
        }}
        itemKey="name"
        itemName={t('admin.teams.itemName')}
        itemPath="/admin/team/{{value}}"
        jsonSchema={jsonSchema}
      />
    </Fragment>
  )
}
