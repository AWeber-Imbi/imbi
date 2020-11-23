import React from 'react'
import { useTranslation } from 'react-i18next'
import { AdminCRUD } from '../../components'

export default () => {
    const { t, i18n } = useTranslation()
    return (
        <AdminCRUD
            addIcon="fas fa-cog"
            columns={[
                {
                    headerStyle: { width: '20%' },
                    name: 'name',
                    required: true,
                    sortable: true,
                    title: `${t('projectType.title')}`,
                },
                {
                    name: 'description',
                    title: `${t('common.descriptionTitle')}`,
                },
                {
                    name: 'slug',
                    title: `${t('projectType.slug')}`,
                },
                {
                    default: 'fas fa-cog',
                    headerStyle: { width: '20%' },
                    isIcon: true,
                    name: 'icon_class',
                    placeholder: 'fas fa-cog',
                    title: `${t('projectType.iconClass')}`,
                },
            ]}
            errorStrings={{
                'duplicate key value violates unique constraint "project_types_pkey"': {
                    column: 'name',
                    message: `${t('projectType.message')}`,
                },
            }}
            itemPath="/admin/project_type"
            itemTitle={t('projectType.title')}
            itemsPath="/settings/project_types"
            itemsTitle={t('projectType.titles')}
            keyField="name"
        />
    )
}
