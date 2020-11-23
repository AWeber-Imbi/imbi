import React, { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AdminCRUD, Loading } from '../../components'
import { useFetch } from '../../hooks'

export default function () {
    const [groups, groupsErrorMessage] = useFetch(
        '/settings/groups',
        undefined,
        false
    )
    const { t } = useTranslation()
    if (groups === undefined) return <Loading />

    return (
        <AdminCRUD
            addIcon="fas fa-users"
            columns={[
                {
                    headerStyle: { width: '30%' },
                    name: 'name',
                    required: true,
                    sortable: true,
                    title: `${t('teams.name')}`,
                },
                {
                    headerStyle: { width: '20%' },
                    name: 'slug',
                    required: true,
                    sortable: true,
                    title: `${t('teams.slug')}`,
                },
                {
                    default: 'fas fa-users',
                    headerStyle: { width: '20%' },
                    isIcon: true,
                    name: 'icon_class',
                    placeholder: 'fas fa-users',
                    title: `${t('teams.iconClass')}`,
                },
                {
                    headerStyle: { width: '40%' },
                    name: 'group',
                    options: groups.map((group) => {
                        return { label: group.name, value: group.name }
                    }),
                    title: `${t('teams.group')}`,
                    type: 'select',
                },
            ]}
            errorStrings={{
                'duplicate key value violates unique constraint "teams_pkey"': {
                    column: 'name',
                    message: `${t('teams.message')}`,
                },
            }}
            itemPath="/admin/team"
            itemTitle={t('teams.title')}
            itemsPath="/settings/teams"
            itemsTitle={t('teams.title')}
            keyField="name"
        />
    )
}
