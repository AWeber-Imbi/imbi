import React from 'react'
import { useTranslation } from 'react-i18next'
import { AdminCRUD, Loading } from '../../components'
import { useFetch } from '../../hooks'

export default function () {
    const [permissions, errorMessage] = useFetch(
        '/settings/permissions',
        undefined,
        true
    )
    const { t } = useTranslation()
    if (permissions === undefined) return <Loading />

    return (
        <AdminCRUD
            addIcon="fas fa-users"
            columns={[
                {
                    headerStyle: { width: '25%' },
                    name: 'name',
                    required: true,
                    sortable: true,
                    title: `${t('groups.name')}`,
                },
                {
                    default: 'internal',
                    headerStyle: { width: '20%' },
                    name: 'group_type',
                    options: [
                        { label: `${t('groups.internal')}`, value: 'internal' },
                        { label: `${t('groups.ldap')}`, value: 'ldap' },
                    ],
                    required: true,
                    sortable: true,
                    title: `${t('groups.groupType')}`,
                    type: 'select',
                },
                {
                    errorHelp: `${t('groups.errorHelp')}`,
                    headerStyle: { width: '35%' },
                    name: 'external_id',
                    title: `${t('groups.externalId')}`,
                },
                {
                    headerStyle: { width: '20%' },
                    editable: false,
                    formatter: renderPermissions,
                    name: 'permissions',
                    title: `${t('groups.permissions')}`,
                },
            ]}
            errorStrings={{
                'duplicate key value violates unique constraint "groups_pkey"': {
                    column: 'name',
                    message: `${t('groups.message')}`,
                },
            }}
            itemPath="/admin/group"
            itemTitle={t('groups.title')}
            itemsPath="/settings/groups"
            itemsTitle={t('groups.titles')}
            keyField="name"
            validationCallback={validateRow}
        />
    )
}

function renderPermissions(values) {
    if (values) {
        return (
            <span>
                {values.map((value) => {
                    return (
                        <span className="badge badge-dark" key={value}>
                            {value}
                        </span>
                    )
                })}
            </span>
        )
    }
}

function validateRow(row) {
    if (row.group_type == 'ldap' && !row.external_id) {
        return { state: 'column_error', column: 'external_id' }
    }
    if (row.group_type == 'internal' && row.external_id !== null) {
        return { state: 'update_column', column: 'external_id', value: null }
    }
    return { state: 'ok' }
}
