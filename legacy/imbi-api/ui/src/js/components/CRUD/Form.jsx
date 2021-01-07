import {compare} from 'fast-json-patch'
import PropTypes from "prop-types"
import React, {useContext, useEffect, useState} from "react"
import {useTranslation} from "react-i18next";
import {validate} from "jsonschema"

import {Alert} from ".."
import {Column, Columns} from "../../schema"
import {FetchContext} from "../../contexts"
import {IconSelect} from "../Forms"
import {httpPost, httpPatch} from "../../utils"

function Field({autoFocus, errorMessage, handleUpdate, value, ...props}) {

  function handleChange(event) {
    event.preventDefault()
    handleUpdate(props.name, event.target.value)
  }

  function handleNumberChange(event) {
    event.preventDefault()
    handleUpdate(props.name, parseInt(event.target.value))
  }

  const numbers = "0123456789"

  return (
    <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:items-start sm:pt-5">
      <label htmlFor={"field-" + props.name} className="block text-sm font-medium text-gray-700 sm:mt-px sm:pt-2">
        {props.title}
      </label>
      <div className="mt-1 sm:mt-0 sm:col-span-2">
        {props.type === "icon" && (
          <IconSelect autoFocus={autoFocus}
                      className={"form-input" + (errorMessage !== null ? " border-red-700" : "")}
                      defaultValue={value}
                      id={"field-" + props.name}
                      name={props.name}
                      onChange={handleChange}
                      placeholder={props.placeholder}/>
        )}
        {props.type === "number" && (
          <input autoComplete={props.name}
                 autoFocus={autoFocus}
                 className={"form-input" + (errorMessage !== null ? " border-red-700" : "")}
                 defaultValue={value !== null ? value.toString() : value}
                 id={"field-" + props.name}
                 name={props.name}
                 onBlur={handleNumberChange}
                 onKeyPress={(event) => {
                   if (!numbers.includes(event.key)) event.preventDefault()
                 }}
                 placeholder={props.placeholder}
                 type="text"/>
        )}
        {props.type === "select" && (
          <select autoFocus={autoFocus}
                  className={"form-input" + (errorMessage !== null ? " border-red-700" : "")}
                  defaultValue={value}
                  id={"field-" + props.name}
                  name={props.name}
                  onChange={handleChange}
                  placeholder={props.placeholder}>
            <option value="" />
            {props.options.map((option) => {
              return (
                <option key={props.name + "-" + option.value} value={option.value}>
                  {option.label}
                </option>
              )
            })}
          </select>
        )}
        {props.type === "text" && (
          <input autoComplete={props.name}
                 autoFocus={autoFocus}
                 className={"form-input" + (errorMessage !== null ? " border-red-700" : "")}
                 defaultValue={value}
                 id={"field-" + props.name}
                 name={props.name}
                 onBlur={handleChange}
                 placeholder={props.placeholder}
                 type="text"/>
        )}
        {props.type === "textarea" && (
          <textarea className={"form-input" + (errorMessage !== null ? " border-red-700" : "")}
                    defaultValue={value}
                    id={"field-" + props.name}
                    name={props.name}
                    onBlur={handleChange}
                    placeholder={props.placeholder}
                    rows="3"/>
        )}
        {errorMessage !== null && (
          <p className="mt-2 text-sm text-red-700 col-span-2">{errorMessage}</p>
        )}
        {errorMessage === null && props.description !== undefined && (
          <p className="mt-2 text-sm text-gray-500 col-span-2">{props.description}</p>
        )}
      </div>
    </div>
  )
}

Field.propTypes = {
  autoFocus: PropTypes.bool.isRequired,
  errorMessage: PropTypes.string,
  handleUpdate: PropTypes.func.isRequired,
  value: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
  ...Column
}

function Form({columns, errorStrings, isEdit, itemKey, itemPath, jsonSchema, onClose, savingTitle, title, values}) {
  const {t} = useTranslation()
  const fetchMethod = useContext(FetchContext)

  const emptyErrors = columns.reduce((result, column) => {
    result[column.name] = null
    return result
  }, {})

  const [errors, setErrors] = useState(emptyErrors)
  const [errorMessage, setErrorMessage] = useState(null)
  const [formReady, setFormReady] = useState(false)
  const [formValues, setFormValues] = useState(columns.reduce((result, column) => {
    result[column.name] = values !== null
      ? (values[column.name] !== undefined ? values[column.name] : null)
      : (column.default !== undefined ? (typeof(column.default) === "function"
                                         ? column.default()
                                         : column.default) : null)
    return result
  }, {}))
  const [originalValues, _] = useState(values)   // eslint-disable-line
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    const result = validate(formValues, jsonSchema)
    if (result.errors.length > 0) {
      const errors = {...emptyErrors}
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
      setErrors({...emptyErrors})
      setFormReady(true)
    }
  }, [formValues])

  function handleFieldUpdate(name, value) {
    setFormValues({...formValues, [name]: value})
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setFormReady(false)
    setSaving(true)
    let result = null
    if (isEdit === true) {
      const patchValue = compare(originalValues, formValues)
      result = await httpPatch(
        fetchMethod, itemPath.replace(/{{value}}/, originalValues[itemKey]),
        patchValue)
    } else {
      result = await httpPost(fetchMethod, itemPath, formValues)
    }
    setSaving(false)
    if (result.success === true) {
      onClose(formValues[itemKey])
    } else {
      setErrorMessage(errorStrings[result.data] !== undefined ? errorStrings[result.data] : result.data)
    }
  }

  return (
    <div className="fixed z-10 inset-0 overflow-y-auto">
      <div className="flex items-end justify-center min-h-screen pt-4 px-4 pb-20 text-center sm:block sm:p-0">
        <div className="fixed inset-0 transition-opacity" aria-hidden="true">
          <div className="absolute inset-0 bg-gray-500 opacity-75" />
        </div>
        <span className="hidden sm:inline-block sm:align-middle sm:h-screen" aria-hidden="true">&#8203;</span>
        <div className="inline-block align-bottom bg-white rounded-lg px-4 pt-5 pb-4 text-left overflow-hidden shadow-xl transform transition-all sm:my-8 sm:align-middle sm:max-w-2xl sm:w-full sm:p-6"
             role="dialog" aria-modal="true" aria-labelledby="modal-headline">
          <h1 className="text-xl text-gray-500 border-b border-gray-400 pb-2 mb-3">{saving ? savingTitle : title}</h1>
          {errorMessage !== null && (
            <Alert className="mb-3" level="error">{errorMessage}</Alert>
          )}
          <form onSubmit={handleSubmit}>
            {columns.map((column, index) => {
              return (<Field autoFocus={index === 0}
                             errorMessage={errors[column.name]}
                             handleUpdate={handleFieldUpdate}
                             key={"field-" + column.name}
                             value={formValues[column.name]}
                             {...column} />)
            })}
            <div className="mt-5 sm:mt-6 text-right border-t border-t-gray-400 pt-5 mt-5 space-x-3">
              <button className={saving ? "btn-disabled": "btn-white"}
                      disabled={saving}
                      onClick={() => {onClose()}}
                      type="button">
                {t("common.cancel")}
              </button>
              <button className={formReady ? "btn-green" : "btn-disabled"}
                      disabled={!formReady}
                      type="submit">
                {saving ? t("common.saving") : t("common.save")}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}

Form.propTypes = {
  columns: Columns.isRequired,
  errorStrings: PropTypes.object.isRequired,
  isEdit: PropTypes.bool.isRequired,
  itemKey: PropTypes.string.isRequired,
  itemPath: PropTypes.string.isRequired,
  jsonSchema: PropTypes.object.isRequired,
  onClose: PropTypes.func.isRequired,
  savingTitle: PropTypes.string.isRequired,
  title: PropTypes.string.isRequired,
  values: PropTypes.object
}

export {Form}
