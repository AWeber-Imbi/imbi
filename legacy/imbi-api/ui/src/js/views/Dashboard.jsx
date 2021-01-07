import React from "react"
import {useTranslation} from "react-i18next"

export function Dashboard() {
  const {t} = useTranslation()
  return (
    <h1 className="text-xl text-bold">{t("common.welcome")}</h1>
  )
}
