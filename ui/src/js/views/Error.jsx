import PropTypes from "prop-types"
import React, {useContext} from "react"
import {useTranslation} from "react-i18next"

import {Error as ErrorComponent} from "../components"
import {setDocumentTitle} from "../utils";
import {SettingsContext} from "../contexts";

function Error({children}) {
  const {t} = useTranslation()
  setDocumentTitle(useContext(SettingsContext), t("error.title"))
  return (
    <ErrorComponent>{{children}}</ErrorComponent>
  )
}

Error.propTypes = {
  children: PropTypes.string.isRequired
}

export {Error}
