import PropTypes from "prop-types";
import React from "react"
import {useTranslation} from "react-i18next"

function Footer({service, version}) {
  const {t} = useTranslation()
  return (
    <footer className="flex-shrink h-10 bg-white border-t border-gray-400 align-middle text-sm p-2 text-gray-500">
      {service} v{version} &mdash; <a href="/api-docs/">{t("footer.apiDocumentation")}</a>
    </footer>
  )
}

Footer.propTypes = {
  service: PropTypes.string,
  version: PropTypes.string
}

export default Footer
