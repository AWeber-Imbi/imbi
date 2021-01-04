import React, {useEffect, useState} from "react"
import {useTranslation} from 'react-i18next'


import {CRUD} from "../../components"
import {jsonSchema} from "../../schema/CookieCutter"
import {useFetch} from "../../hooks"

export function CookieCutters() {
  const [projectTypes, dataErrorMessage] = useFetch("/settings/project_types", [], false, 0)
  const [projectTypeOptions, setProjectTypeOptions] = useState(projectTypes)

  useEffect(() => {
    const options = []
    projectTypes.map((projectType) => {
      options.push({
        label: projectType.name,
        value: projectType.name
      })
    })
    setProjectTypeOptions(options)
  }, [projectTypes])

  const {t} = useTranslation()
  return (
    <CRUD addPath="/admin/cookie_cutter"
          collectionIcon="fas cookie"
          collectionName={t("admin.cookieCutters.collectionName")}
          collectionPath="/settings/cookie_cutters"
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
              title: t("admin.cookieCutters.type"),
              name: "type",
              type: "select",
              options: [
                {"label": "Dashboard", value: "dashboard"},
                {"label": "Project", value: "project"},
              ],
              tableOptions: {
                className: "min-w-sm"
              }
            },
            {
              title: t("admin.projectTypes.itemName"),
              name: "project_type",
              type: "select",
              options: projectTypeOptions,
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
              title: t("admin.cookieCutters.url"),
              name: "url",
              description: t("admin.cookieCutters.urlDescription"),
              type: "text",
              tableOptions: {
                className: "w-min"
              }
            }
          ]}
          errorStrings={{
            "Unique Violation":  t("admin.cookieCutters.errors.uniqueViolation")
          }}
          itemKey="name"
          itemName={t("admin.cookieCutters.itemName")}
          jsonSchema={jsonSchema}/>
  )
}
