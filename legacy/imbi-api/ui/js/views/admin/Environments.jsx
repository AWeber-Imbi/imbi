import React from 'react'
import { useTranslation } from 'react-i18next'
import { AdminCRUD } from '../../components'

export default () => {
    const { t } = useTranslation()
    return (
        <AdminCRUD
            addIcon="fas fa-mountain"
            columns={[
                {
                    headerStyle: { width: '20%' },
                    name: 'name',
                    required: true,
                    sortable: true,
                    title: `${t('environment.title')}`,
                },
                {
                    headerStyle: { width: '65%' },
                    name: 'description',
                    title: `${t('common.descriptionTitle')}`,
                },
                {
                    default: 'fas fa-mountain',
                    headerStyle: { width: '15%' },
                    isIcon: true,
                    name: 'icon_class',
                    placeholder: 'fas fa-mountain',
                    title: `${t('environment.iconClass')}`,
                },
            ]}
            errorStrings={{
                'duplicate key value violates unique constraint "environments_pkey"': {
                    field: 'name',
                    message: `${t('environment.message')}`,
                },
            }}
            itemPath="/admin/environment"
            itemTitle={t('environment.title')}
            itemsPath="/settings/environments"
            itemsTitle={t('environment.titles')}
            keyField="name"
        />
    )
}
