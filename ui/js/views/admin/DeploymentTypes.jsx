import React from 'react'
import { useTranslation } from 'react-i18next'
import { AdminCRUD } from '../../components'

export default () => {
    const { t } = useTranslation()
    return (
        <AdminCRUD
            addIcon="fas fa-box"
            columns={[
                {
                    headerStyle: { width: '30%' },
                    name: 'name',
                    required: true,
                    sortable: true,
                    title: `${t('deploymentType.title')}`,
                },
                {
                    name: 'description',
                    title: `${t('common.descriptionTitle')}`,
                },
                {
                    default: 'fas fa-box',
                    headerStyle: { width: '20%' },
                    isIcon: true,
                    name: 'icon_class',
                    placeholder: 'fas fa-box',
                    title: `${t('deploymentType.iconClass')}`,
                },
            ]}
            errorStrings={{
                'duplicate key value violates unique constraint "deployment_types_pkey"': {
                    column: 'name',
                    message: `${t('deploymentType.message')}`,
                },
            }}
            itemPath="/admin/deployment_type"
            itemTitle={t('deploymentType.title')}
            itemsPath="/settings/deployment_types"
            itemsTitle={t('deploymentType.titles')}
            keyField="name"
        />
    )
}
