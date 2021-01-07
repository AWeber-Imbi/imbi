import React from "react"
import {useTranslation} from 'react-i18next'

import {jsonSchema} from "../../schema/ConfigurationSystem"

import {CRUD} from "../../components"

export function ConfigurationSystems() {
  const {t} = useTranslation()
  return (
    <CRUD addPath="/admin/configuration_system"
          collectionIcon="fas box"
          collectionName={t("admin.configurationSystems.collectionName")}
          collectionPath="/settings/configuration_systems"
          columns={[
            {
              title: t("common.name"),
              name: "name",
              type: "text",
              tableOptions: {
                className: "min-w-sm"
              }
            },
            {
              title: t("common.description"),
              name: "description",
              type: "textarea",
              tableOptions: {
                className: "max-w-lg truncate"
              }
            },
            {
              title: t("common.iconClass"),
              name: "icon_class",
              type: "icon",
              placeholder: "fas sliders-h",
              default: "fas sliders-h",
              tableOptions: {
                className: "w-min"
              }
            }
          ]}
          errorStrings={{
            "Unique Violation":  t("admin.configurationSystems.errors.uniqueViolation")
          }}
          itemKey="name"
          itemName={t("admin.configurationSystems.itemName")}
          itemPath="/admin/configuration_system/{{value}}"
          jsonSchema={jsonSchema}/>
  )
}
