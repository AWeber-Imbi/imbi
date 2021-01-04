import React from "react"
import {useTranslation} from 'react-i18next'

import {jsonSchema} from "../../schema/ProjectType"

import {CRUD} from "../../components"

export function ProjectTypes() {
  const {t} = useTranslation()
  return (
    <CRUD addPath="/admin/project_type"
          collectionIcon="fas cubes"
          collectionName={t("admin.projectTypes.collectionName")}
          collectionPath="/settings/project_types"
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
              title: t("common.slug"),
              name: "slug",
              type: "text",
              description: t("admin.projectTypes.slugDescription"),
              tableOptions: {
                className: "max-w-lg truncate"
              }
            },
            {
              title: t("common.description"),
              name: "description",
              type: "textarea",
              tableOptions: {
                hide: true
              }
            },
            {
              title: t("common.iconClass"),
              name: "icon_class",
              type: "icon",
              placeholder: "fas cubes",
              default: "fas cubes",
              tableOptions: {
                className: "w-min"
              }
            }
          ]}
          errorStrings={{
            "Unique Violation":  t("admin.projectTypes.errors.uniqueViolation")
          }}
          itemKey="name"
          itemName={t("admin.projectTypes.itemName")}
          jsonSchema={jsonSchema}/>
  )
}
