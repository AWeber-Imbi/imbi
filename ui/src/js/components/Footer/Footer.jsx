import PropTypes from 'prop-types'
import React from 'react'
import { useTranslation } from 'react-i18next'

import { Logo } from './AWeber'

function Footer({ service, version }) {
  const { t } = useTranslation()
  return (
    <footer className="flex-shrink flex h-10 bg-white border-t border-gray-400 align-middle text-sm text-gray-500">
      <div className="flex-auto p-2">
        {service} v{version} &mdash;{' '}
        <a href="/api-docs/">{t('footer.apiDocumentation')}</a>
      </div>
      <div className="flex-shrink h-8 w-8 p-1 mr-2">
        <a href="https://aweber.com">
          <Logo className="text-blue-700 h-8 w-8" />
        </a>
      </div>
    </footer>
  )
}

Footer.propTypes = {
  service: PropTypes.string,
  version: PropTypes.string
}

export { Footer }
