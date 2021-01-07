import React, {Fragment, useContext, useEffect, useState} from "react"
import {useTranslation} from 'react-i18next'

import {CRUD, Error} from "../../components"
import {FetchContext} from "../../contexts"
import {fetchProjectTypes} from "../../settings"
import {jsonSchema} from "../../schema/CookieCutter"

export function CookieCutters() {
  const fetch = useContext(FetchContext)
  const [errorMessage, setErrorMessage] = useState(null)
  const [projectTypes, setProjectTypes] = useState(null)
  const {t} = useTranslation()

  useEffect(() => {
    if (projectTypes === null) {
      fetchProjectTypes(
        fetch, true,
        (result) => {
          setProjectTypes(result)
        },
        (error) => {setErrorMessage(error)})
    }
  }, [projectTypes])

  return (
    <Fragment>
      {errorMessage && <Error>{{errorMessage}}</Error>}
      {!projectTypes && <div>Loading</div>}
      {projectTypes && (
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
                options: projectTypes,
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
              "Unique Violation": t("admin.cookieCutters.errors.uniqueViolation")
            }}
            itemKey="name"
            itemName={t("admin.cookieCutters.itemName")}
            itemPath="/admin/cookie_cutter/{{value}}"
            jsonSchema={jsonSchema}/>)}
    </Fragment>
  )
}
