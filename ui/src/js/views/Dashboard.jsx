import React from "react"
import {useTranslation} from "react-i18next"

import {ContentArea} from "../components/"

export function Dashboard() {
  const {t} = useTranslation()
  return (
    <ContentArea pageIcon="fas chart-line" pageTitle={t("common.welcome")} />
  )
}
