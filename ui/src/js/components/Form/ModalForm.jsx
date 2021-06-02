import PropTypes from 'prop-types'
import React, { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { validate } from 'jsonschema'

import { Alert, Button, Modal } from '..'
import { Columns } from '../../schema'
import { Field } from './Field'
import { isFunction } from '../../utils'

function ModalForm({
  columns,
  formType,
  jsonSchema,
  onClose,
  onSubmit,
  savingTitle,
  title,
  values
}) {
  const { t } = useTranslation()

  const emptyErrors = columns.reduce((value, column) => {
    value[column.name] = null
    return value
  }, {})

  const [errors, setErrors] = useState(emptyErrors)
  const [errorMessage, setErrorMessage] = useState(null)
  const formColumns = useState(
    columns.filter(
      (column) => (formType === 'add' && column.omitOnAdd === true) !== true
    )
  )[0]

  const [formReady, setFormReady] = useState(false)
  const [formValues, setFormValues] = useState(
    formColumns.reduce((accumulator, column) => {
      let columnValue = values !== null ? values[column.name] : undefined
      if (columnValue === undefined)
        columnValue = isFunction(column.default)
          ? column.default()
          : column.default
      accumulator[column.name] = columnValue !== undefined ? columnValue : null
      return accumulator
    }, {})
  )
  const [ignoreErrors, setIgnoreErrors] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    const result = validate(formValues, jsonSchema)
    //console.debug('Errors', result.errors)
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
    <Modal>
      <form onSubmit={handleSubmit}>
        <Modal.Title>{saving ? savingTitle : title}</Modal.Title>
        <Modal.Body>
          {ignoreErrors !== true && errorMessage !== null && (
            <Alert className="mb-3" level="error">
              {errorMessage}
            </Alert>
          )}
          {formColumns.map((column, index) => {
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
        </Modal.Body>
        <Modal.Footer>
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
        </Modal.Footer>
      </form>
    </Modal>
  )
}

ModalForm.defaultProps = {
  formType: 'edit'
}

ModalForm.propTypes = {
  columns: Columns.isRequired,
  formType: PropTypes.oneOf(['add', 'edit']),
  jsonSchema: PropTypes.object.isRequired,
  onClose: PropTypes.func.isRequired,
  onSubmit: PropTypes.func.isRequired,
  savingTitle: PropTypes.string.isRequired,
  title: PropTypes.string.isRequired,
  values: PropTypes.object
}

export { ModalForm }
