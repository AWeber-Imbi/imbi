import PropTypes from 'prop-types'
import React, { Fragment, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { validate } from 'jsonschema'

import { Alert, Button, Modal } from '..'
import { Columns } from '../../schema'
import { Field } from './Field'

function Form({
  columns,
  jsonSchema,
  onClose,
  onSubmit,
  savingTitle,
  title,
  values
}) {
  const { t } = useTranslation()

  const emptyErrors = columns.reduce((result, column) => {
    result[column.name] = null
    return result
  }, {})

  const [errors, setErrors] = useState(emptyErrors)
  const [errorMessage, setErrorMessage] = useState(null)
  const [formReady, setFormReady] = useState(false)
  const [formValues, setFormValues] = useState(
    columns.reduce((result, column) => {
      result[column.name] =
        values !== null
          ? values[column.name] !== undefined
            ? values[column.name]
            : null
          : column.default !== undefined
          ? typeof column.default === 'function'
            ? column.default()
            : column.default
          : null
      return result
    }, {})
  )
  const [ignoreErrors, setIgnoreErrors] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    const result = validate(formValues, jsonSchema)
    if (result.errors.length > 0) {
      const errors = { ...emptyErrors }
      result.errors.map((err) => {
        err.path.map((field) => {
          if (formValues[field] !== null) {
            errors[field] = err.message
          }
        })
      })
      setErrors(errors)
      setFormReady(false)
    } else {
      setErrors({ ...emptyErrors })
      setFormReady(true)
    }
  }, [formValues])

  function handleFieldUpdate(name, value) {
    setFormValues({ ...formValues, [name]: value })
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setSaving(true)
    const result = await onSubmit(formValues)
    setSaving(false)
    if (result !== null) {
      setErrorMessage(result)
      setFormReady(false)
    }
  }

  return (
    <Modal title={saving ? savingTitle : title}>
      <Fragment>
        {ignoreErrors !== true && errorMessage !== null && (
          <Alert className="mb-3" level="error">
            {errorMessage}
          </Alert>
        )}
        <form onSubmit={handleSubmit}>
          {columns.map((column, index) => {
            return (
              <Field
                autoFocus={index === 0}
                errorMessage={errors[column.name]}
                onChange={handleFieldUpdate}
                key={'field-' + column.name}
                value={formValues[column.name]}
                {...column}
              />
            )
          })}
          <div className="mt-5 sm:mt-6 text-right border-t border-gray-400 pt-5 mt-5 space-x-3">
            <Button
              className={'btn-white'}
              disabled={saving}
              onClick={() => {
                setIgnoreErrors(true)
                onClose()
              }}>
              {t('common.cancel')}
            </Button>
            <Button
              className={'btn-green'}
              disabled={!formReady && !saving}
              type="submit">
              {saving ? t('common.saving') : t('common.save')}
            </Button>
          </div>
        </form>
      </Fragment>
    </Modal>
  )
}

Form.propTypes = {
  columns: Columns.isRequired,
  jsonSchema: PropTypes.object.isRequired,
  onClose: PropTypes.func.isRequired,
  onSubmit: PropTypes.func.isRequired,
  savingTitle: PropTypes.string.isRequired,
  title: PropTypes.string.isRequired,
  values: PropTypes.object
}

export { Form }
