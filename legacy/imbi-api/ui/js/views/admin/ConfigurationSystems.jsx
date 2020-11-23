import React from 'react'
import { useTranslation } from 'react-i18next'

import { AdminCRUD } from '../../components'

export default () => {
    const { t } = useTranslation()
    return (
        <AdminCRUD
            addIcon="fas fa-sliders-h"
            columns={[
                {
                    headerStyle: { width: '30%' },
                    name: 'name',
                    placeholder: `${t(
                        'configurationSystem.configurationSystemName'
                    )}`,
                    required: true,
                    sortable: true,
                    title: `${t(
                        'configurationSystem.configuartionSystempPlaceholder'
                    )}`,
                },
                {
                    name: 'description',
                    placeholder: `${t('common.descriptionPlaceholder')}`,
                    title: `${t('common.descriptionTitle')}`,
                },
                {
                    default: 'fas fa-sliders-h',
                    headerStyle: { width: '20%' },
                    isIcon: true,
                    name: 'icon_class',
                    placeholder: 'fas fa-sliders-h',
                    title: `${t('configurationSystem.iconClass')}`,
                },
            ]}
            errorStrings={{
                'duplicate key value violates unique constraint "configuration_systems_pkey"': {
                    column: 'name',
                    message: `${t('configurationSystem.errormsg')}`,
                },
            }}
            itemPath="/admin/configuration_system"
            itemsPath="/settings/configuration_systems"
            itemTitle={t('configurationSystem.configurationSystemName')}
            itemsTitle={t('configurationSystem.configurationSystem')}
            keyField="name"
        />
    )
}
