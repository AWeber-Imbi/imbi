import React from 'react'
import { useTranslation } from 'react-i18next'
import { AdminCRUD } from '../../components'

export default () => {
    const { t } = useTranslation()
    return (
        <AdminCRUD
            addIcon="fas fa-hand-point-right"
            columns={[
                {
                    headerStyle: { width: '30%' },
                    name: 'name',
                    required: true,
                    sortable: true,
                    title: `${t('orchestration.title')}`,
                },
                {
                    name: 'description',
                    title: `${t('common.descriptionTitle')}`,
                },
                {
                    default: 'fas fa-hand-point-right',
                    headerStyle: { width: '20%' },
                    isIcon: true,
                    name: 'icon_class',
                    placeholder: 'fas fa-hand-point-right',
                    title: `${t('orchestration.iconClass')}`,
                },
            ]}
            errorStrings={{
                'duplicate key value violates unique constraint "orchestration_systems_pkey"': {
                    column: 'name',
                    message: `${t('orchestration.message')}`,
                },
            }}
            itemPath="/admin/orchestration_system"
            itemTitle={t('orchestration.title')}
            itemsPath="/settings/orchestration_systems"
            itemsTitle={t('orchestration.titles')}
            keyField="name"
        />
    )
}
