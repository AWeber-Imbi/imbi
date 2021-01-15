import React from "react"
import {useTranslation} from 'react-i18next'

import {jsonSchema} from "../../schema/ProjectLinkType"

import {CRUD} from "../../components"

export function ProjectLinkTypes() {
  const {t} = useTranslation()
  return (
    <CRUD addPath="/admin/project_link_type"
          collectionIcon="fas external-link-alt"
          collectionName={t("admin.projectLinkTypes.collectionName")}
          collectionPath="/settings/project_link_types"
          columns={[
            {
              title: t("admin.projectLinkTypes.linkType"),
              name: "link_type",
              type: "text",
            },
            {
              title: t("common.iconClass"),
              name: "icon_class",
              type: "icon",
              placeholder: "fas external-link-alt",
              default: "fas external-link-alt",
            }
          ]}
          errorStrings={{
            "Unique Violation": t("admin.projectLinkTypes.errors.uniqueViolation")
          }}
          itemKey="link_type"
          itemName={t("admin.projectLinkTypes.itemName")}
          itemPath="/admin/project_link_type/{{value}}"
          jsonSchema={jsonSchema}/>
  )
}
