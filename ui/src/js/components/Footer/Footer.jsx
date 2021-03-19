import PropTypes from 'prop-types'
import React from 'react'
import { useTranslation } from 'react-i18next'

import { Icon } from '../'
import { Logo } from './AWeber'

function Footer({ linkIcon, linkText, linkURL, service, version }) {
  const { t } = useTranslation()
  return (
    <footer className="flex-shrink flex flex-row h-10 bg-white border-t border-gray-400 align-middle text-sm text-gray-500">
      <div className="ml-2 p-2 w-4/12">
        {service} v{version} &mdash;{' '}
        <a href="/api-docs/">{t('footer.apiDocumentation')}</a>
      </div>
      <div className="p-2 text-center  w-4/12">
        {linkURL !== '' && (
          <a href={linkURL} rel="noreferrer" target="_blank">
            {linkIcon && <Icon icon={linkIcon} className="mr-2" />}
            {linkText}
          </a>
        )}
        {linkText === '' && linkText !== '' && linkText}
      </div>
      <div className="flex mr-2 p-1 justify-end w-4/12">
        <a href="https://aweber.com" style={{ width: '32px', height: '32px' }}>
          <Logo className="text-blue-700" />
        </a>
      </div>
    </footer>
  )
}

Footer.propTypes = {
  linkIcon: PropTypes.string,
  linkText: PropTypes.string,
  linkURL: PropTypes.string,
  service: PropTypes.string,
  version: PropTypes.string
}

export { Footer }
