import React from 'react'
import { useTranslation } from 'react-i18next'
import { AdminCRUD } from '../../components'

export default () => {
    const { t } = useTranslation()
    return (
        <AdminCRUD
            addIcon="fas fa-building"
            columns={[
                {
                    headerStyle: { width: '30%' },
                    name: 'name',
                    required: true,
                    sortable: true,
                    title: `${t('dataCenter.dataCenter')}`,
                },
                {
                    name: 'description',
                    title: `${t('common.descriptionTitle')}`,
                },
                {
                    default: 'fas fa-building',
                    headerStyle: { width: '20%' },
                    isIcon: true,
                    name: 'icon_class',
                    placeholder: 'fas fa-building',
                    title: `${t('dataCenter.iconClass')}`,
                },
            ]}
            errorStrings={{
                'duplicate key value violates unique constraint "data_centers_pkey"': {
                    column: 'name',
                    message: `${t('dataCenter.message')}`,
                },
            }}
            itemPath="/admin/data_center"
            itemTitle={t('dataCenter.dataCenter')}
            itemsPath="/settings/data_centers"
            itemsTitle={t('dataCenter.dataCenters')}
            keyField="name"
        />
    )
}
