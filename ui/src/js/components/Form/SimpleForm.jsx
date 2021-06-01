import PropTypes from 'prop-types'
import React from 'react'
import { useTranslation } from 'react-i18next'

import { Alert, Button } from '..'
import { Field } from './Field'

function SimpleForm({
  children,
  errorMessage,
  onCancel,
  onSubmit,
  ready,
  saving,
  submitButtonText,
  submitSavingText
}) {
  const { t } = useTranslation()
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        onSubmit()
      }}>
      {errorMessage !== null && (
        <Alert className="mb-3" level="error">
          {errorMessage}
        </Alert>
      )}
      {children}
      <div className="mt-5 sm:mt-6 text-right border-t border-gray-400 pt-5 mt-5 space-x-3">
        <Button
          className={'btn-white'}
          disabled={saving === true}
          onClick={onCancel}>
          {t('common.cancel')}
        </Button>
        <Button
          className={'btn-green'}
          disabled={ready === false || saving === true}
          type="submit">
          {saving
            ? submitSavingText
              ? submitSavingText
              : t('common.save')
            : submitButtonText
            ? submitButtonText
            : t('common.saving')}
        </Button>
      </div>
    </form>
  )
}
SimpleForm.defaultPropTypes = {
  errorMessage: null,
  ready: false,
  saving: false,
  submitSavingText: null,
  submitButtonText: null
}
SimpleForm.propTypes = {
  children: PropTypes.arrayOf(Field),
  errorMessage: PropTypes.string,
  onCancel: PropTypes.func.isRequired,
  onSubmit: PropTypes.func.isRequired,
  ready: PropTypes.bool.isRequired,
  saving: PropTypes.bool.isRequired,
  submitButtonText: PropTypes.string,
  submitSavingText: PropTypes.string
}
export { SimpleForm }
