import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CRUDIndex } from '../../components'
import { useFetch } from '../../hooks'

export default function (props) {
    const [data, dataErrorMessage] = useFetch('/projects/', undefined)
    const [errorMessage, setErrorMessage] = useState(undefined)
    const [filter, setFilter] = useState(undefined)
    const [successMessage, setSuccessMessage] = useState(undefined)
    const { t } = useTranslation()
    if (dataErrorMessage !== undefined) setErrorMessage(dataErrorMessage)

    const updatedData =
        data &&
        data.map((item) => {
            return { ...item, editable: true }
        })

    return (
        <CRUDIndex
            addPath="/project/add"
            breadcrumbItems={[
                {
                    title: `${t('inventory.projects')}`,
                    path: '/projects/',
                },
            ]}
            columns={[
                {
                    name: 'name',
                    sortable: true,
                    title: `${t('inventory.name')}`,
                },
                {
                    name: 'owned_by',
                    sortable: true,
                    title: `${t('inventory.team')}`,
                },
                {
                    name: 'data_center',
                    sortable: true,
                    title: `${t('inventory.dataCenter')}`,
                },
                {
                    name: 'project_type',
                    sortable: true,
                    title: `${t('inventory.projectType')}`,
                },
                {
                    name: 'id',
                    sortable: false,
                    title: `${t('inventory.edit')}`,
                },
            ]}
            data={updatedData}
            errorMessage={errorMessage}
            keyField="id"
            sortColumn="name"
            sortDirection="asc"
            title={t('inventory.project')}
        />
    )
}
