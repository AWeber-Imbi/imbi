import React from "react"
import {useTranslation} from 'react-i18next'

import {ConfigurationSystem} from "../../schema"

import {CRUD} from "../../components"

function ConfigurationSystems() {
  const {t} = useTranslation()
  return (
    <CRUD addButton={t("admin.configurationSystems.createNew")}
          columns={[
            {
              title: t("common.name"),
              name: "name",
              type: "text"
            },
            {
              title: t("common.description"),
              name: "description",
              type: "textarea"
            },
            {
              title: t("common.iconClass"),
              name: "icon_class",
              type: "icon",
              placeholder: "fa-sliders-h",
              default: "fa-sliders-h",
            }
          ]}
          schema={ConfigurationSystem}
          errorStrings={{
            "duplicate key value violates unique constraint \"configuration_systems_pkey\"": {
              column: "name",
              message: t("admin.configurationSystems.errors.duplicateKey"),
            },
          }}
          itemPath="/admin/configuration_system"
          itemsPath="/settings/configuration_systems"
          itemTitle={t("admin.configurationSystems.singular")}
          itemsTitle={t("admin.configurationSystems.plural")}
          keyField="name"/>
  )
}

export default ConfigurationSystems
