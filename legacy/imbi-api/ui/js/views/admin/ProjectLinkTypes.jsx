import React from 'react'
import { useTranslation } from 'react-i18next'
import { AdminCRUD } from '../../components'

export default () => {
    const { t } = useTranslation()
    return (
        <AdminCRUD
            addIcon="fas fa-link"
            columns={[
                {
                    name: 'link_type',
                    required: true,
                    sortable: true,
                    title: `${t('projectLinkType.title')}`,
                },
                {
                    default: 'fas fa-link',
                    headerStyle: { width: '30%' },
                    isIcon: true,
                    name: 'icon_class',
                    placeholder: 'fas fa-link',
                    title: `${t('projectLinkType.iconClass')}`,
                },
            ]}
            errorStrings={{
                'duplicate key value violates unique constraint "project_link_types_pkey"': {
                    column: 'link_type',
                    message: `${t('projectLinkType.message')}`,
                },
            }}
            itemPath="/admin/project_link_type"
            itemTitle={t('projectLinkType.title')}
            itemsPath="/settings/project_link_types"
            itemsTitle={t('projectLinkType.titles')}
            keyField="link_type"
        />
    )
}
