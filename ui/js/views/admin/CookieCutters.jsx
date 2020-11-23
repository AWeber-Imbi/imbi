import React, { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AdminCRUD, Loading } from '../../components'
import { useFetch } from '../../hooks'

export default function () {
    const [projectTypes, projectTypesErrorMessage] = useFetch(
        '/settings/project_types',
        undefined,
        false
    )
    const { t } = useTranslation()

    if (projectTypes === undefined) return <Loading />

    return (
        <AdminCRUD
            addIcon="fas fa-cookie"
            columns={[
                {
                    headerStyle: { width: '15%' },
                    name: 'name',
                    required: true,
                    sortable: true,
                    title: `${t('common.name')}`,
                },
                {
                    headerStyle: { width: '10%' },
                    name: 'type',
                    options: [
                        {
                            label: `${t('cookieCutter.dashboard')}`,
                            value: 'dashboard',
                        },
                        {
                            label: `${t('cookieCutter.project')}`,
                            value: 'project',
                        },
                    ],
                    placeholder: `${t('cookieCutter.selectType')}`,
                    required: true,
                    sortable: true,
                    title: `${t('cookieCutter.type')}`,
                    type: 'select',
                },
                {
                    headerStyle: { width: '15%' },
                    name: 'project_type',
                    title: `${t('cookieCutter.projectType')}`,
                    options: projectTypes.map((row) => {
                        return { label: row.name, value: row.name }
                    }),
                    placeholder: `${t('cookieCutter.selectProjectType')}`,
                    required: true,
                    type: 'select',
                },
                {
                    name: 'description',
                    title: `${t('common.description')}`,
                },
                {
                    headerStyle: { width: '35%' },
                    name: 'url',
                    required: true,
                    title: `${t('common.git')}`,
                },
            ]}
            errorStrings={{
                'duplicate key value violates unique constraint "cookie_cutters_pkey"': {
                    column: 'name',
                    message: `${t('cookieCutter.errormsg')}`,
                },
            }}
            itemPath="/admin/cookie_cutter"
            itemTitle={t('cookieCutter.cookieTitle')}
            itemsPath="/settings/cookie_cutters"
            itemsTitle={t('cookieCutter.cookieTitles')}
            keyField="name"
        />
    )
}
