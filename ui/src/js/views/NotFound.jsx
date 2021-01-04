import React, {useContext} from "react"
import {useTranslation} from "react-i18next"

import {Icon} from "../components";
import {setDocumentTitle} from "../utils"
import {SettingsContext} from "../contexts"

export function NotFound() {
  const settings = useContext(SettingsContext)
  const {t} = useTranslation()
  setDocumentTitle(settings, t("error.title"))
  return (
    <div className="container mx-auto my-auto max-w-xs bg-red-50 shadow rounded-lg p-5 text-red-700">
      <Icon icon="fas exclamation-circle" />
      <span className="pl-1">
        <span className="font-bold">{t("error.title")}:</span> 404 &ndash; {t("error.notFound")}
      </span>
    </div>
  )
}

export default NotFound
