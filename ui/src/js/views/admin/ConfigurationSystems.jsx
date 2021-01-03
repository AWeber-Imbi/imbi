import React from "react"
import {useTranslation} from 'react-i18next'

import {jsonSchema} from "../../schema/ConfigurationSystem"

import {CRUD} from "../../components"

function ConfigurationSystems() {
  const {t} = useTranslation()
  return (
    <CRUD addPath="/admin/configuration_system"
          collectionName={t("admin.configurationSystems.collectionName")}
          collectionPath="/settings/configuration_systems"
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
              placeholder: "fas sliders-h",
              default: "fas sliders-h",
            }
          ]}
          errorStrings={{
            "Unique Violation":  t("admin.configurationSystems.errors.uniqueViolation")
          }}
          itemKey="name"
          itemName={t("admin.configurationSystems.itemName")}
          jsonSchema={jsonSchema}/>
  )
}

export default ConfigurationSystems
