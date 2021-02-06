import React from 'react'
import { useTranslation } from 'react-i18next'

import { Form } from '../../components'
import { setDocumentTitle } from '../../utils'

function Settings() {
  const { t } = useTranslation()
  setDocumentTitle(t('user.settings.title'))
  return (
    <Form.MultiSectionForm
      title={t('user.settings.title')}
      disabled={false}
      icon="fas user-cog"
      sideBarLinks={[
        { href: '#tokens', label: t('user.settings.authenticationTokens') }
      ]}>
      <Form.Section
        name="api"
        icon="fas id-badge"
        title={t('user.settings.authenticationTokens')}
        firstSection={true}>
        Content
      </Form.Section>
    </Form.MultiSectionForm>
  )
}
export { Settings }
