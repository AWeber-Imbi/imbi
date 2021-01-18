import React from "react"
import {useTranslation} from 'react-i18next'

import {jsonSchema} from "../../schema/Environments"

import {CRUD} from "../../components"

export function Environments() {
  const {t} = useTranslation()
  return (
    <CRUD addPath="/admin/environment"
          collectionIcon="fas tree"
          collectionName={t("admin.environments.collectionName")}
          collectionPath="/settings/environments"
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
              title: t("common.textClass"),
              name: "text_class",
              type: "text",
              placeholder: "",
              default: "",
              tableOptions: {
                className: "w-min"
              }
            },
            {
              title: t("common.iconClass"),
              name: "icon_class",
              type: "icon",
              placeholder: "fas tree",
              default: "fas tree",
              tableOptions: {
                className: "w-min"
              }
            }
          ]}
          errorStrings={{
            "Unique Violation":  t("admin.projectTypes.errors.uniqueViolation")
          }}
          itemKey="name"
          itemName={t("admin.environments.itemName")}
          itemPath="/admin/environment/{{value}}"
          jsonSchema={jsonSchema}/>
  )
}
