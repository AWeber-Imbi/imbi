import PropTypes from "prop-types"
import React, {useContext, useState} from "react"
import {useTranslation} from "react-i18next";
import {validate} from "jsonschema"

import {Alert} from ".."
import {Column, Columns} from "../../schema"
import {FetchContext} from "../../contexts"
import {IconSelect} from "../Forms"
import {httpPost} from "../../utils"

function FormField({autoFocus, jsonSchema, setErrorState, setFormValue, ...props}) {
  const [error, setError] = useState(null)

  function validateValue(e) {
    e.preventDefault()
    const result = validate(e.target.value, jsonSchema)
    if (result.errors.length > 0) {
      result.errors.map((err) => {
        setError(err.message)
      })
      setErrorState(props.name, true)
    } else {
      if (error !== null)
      {
        setError(null)
        setErrorState(props.name, false)
      }
    }
    setFormValue(props.name, e.target.value)
  }

  return (
    <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:items-start sm:pt-5">
      <label htmlFor={"field-" + props.name} className="block text-sm font-medium text-gray-700 sm:mt-px sm:pt-2">
        {props.title}
      </label>
      <div className="mt-1 sm:mt-0 sm:col-span-2">
        {props.type === "icon" && (
          <IconSelect autoFocus={autoFocus}
                      className={"form-input" + (error !== null ? " border-red-700" : "")}
                      defaultValue={props.default}
                      id={"field-" + props.name}
                      name={props.name}
                      onChange={validateValue}
                      placeholder={props.placeholder}  />
        )}
        {props.type === "select" && (
          <select autoFocus={autoFocus}
                  className={"form-input" + (error !== null ? " border-red-700" : "")}
                  defaultValue={props.default}
                  id={"field-" + props.name}
                  name={props.name}
                  onChange={validateValue}
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
                 className={"form-input" + (error !== null ? " border-red-700" : "")}
                 id={"field-" + props.name}
                 name={props.name}
                 onBlur={validateValue}
                 placeholder={props.placeholder}
                 type="text" />
        )}
        {props.type === "textarea" && (
          <textarea className={"form-input" + (error !== null ? " border-red-700" : "")}
                    id={"field-" + props.name}
                    name={props.name}
                    onBlur={validateValue}
                    placeholder={props.placeholder}
                    rows="3" />
        )}
        {error !== null && (
          <p className="mt-2 text-sm text-red-700 col-span-2">{error}</p>
        )}
        {error === null && props.description !== undefined && (
          <p className="mt-2 text-sm text-gray-500 col-span-2">{props.description}</p>
        )}
      </div>
    </div>
  )
}

FormField.propTypes = {
  autoFocus: PropTypes.bool.isRequired,
  jsonSchema: PropTypes.object.isRequired,
  setErrorState: PropTypes.func.isRequired,
  setFormValue: PropTypes.func.isRequired,
  ...Column
}

function AddForm({addPath, columns, errorStrings, itemKey, jsonSchema, onClose, title}) {
  const {t} = useTranslation()
  const fetchMethod = useContext(FetchContext)

  const initialFormValues = {}
  columns.map((column) => {initialFormValues[column.name] = column.default !== undefined ? column.default : ""})

  const [state, setState] = useState({
    errors: [],
    errorMessage: null,
    errorValues: {},
    formValues: initialFormValues})

  function onFieldErrorState(name, value) {
    if (value === true) {
      if (!state.errors.includes(name))
        setState({...state, errors: state.errors.concat([name])})
    } else {
      setState({...state, errors: state.errors.filter(val => val !== name)})
    }
  }
  onFieldErrorState.propTypes = {
    name: PropTypes.string.isRequired,
    value: PropTypes.bool.isRequired
  }

  function onFormValueUpdate(name, value) {
    let newState = {...state, formValues: {...state.formValues, [name]: value}}
    if (state.errorMessage !== null && state.errorValues[name] !== value) {
      newState.errorMessage = null
      newState.errorValues = {}
    }
    setState(newState)
  }
  onFormValueUpdate.propTypes = {
    name: PropTypes.string.isRequired,
    value: PropTypes.bool.isRequired
  }

  async function onSubmit(e) {
    e.preventDefault()
    const result = await httpPost(fetchMethod, addPath, state.formValues)
    if (result.success === true) {
      onClose(state.formValues[itemKey])
    } else {
      setState({
        ...state,
        errorMessage: errorStrings[result.data] !== undefined ? errorStrings[result.data] : result.data,
        errorValues: state.formValues})
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
          <h1 className="text-xl text-gray-500 border-b border-gray-400 pb-2 mb-3">{title}</h1>
          {state.errorMessage !== null && (
            <Alert className="mb-3" level="error">{state.errorMessage}</Alert>
          )}
          <form onSubmit={onSubmit}>
            {columns.map((column, index) => {
              return (<FormField autoFocus={index === 0}
                                 jsonSchema={jsonSchema.properties[column.name]}
                                 key={"field-" + column.name}
                                 setErrorState={onFieldErrorState}
                                 setFormValue={onFormValueUpdate}
                                 {...column} />)
            })}
            <div className="mt-5 sm:mt-6 text-right border-t border-t-gray-400 pt-5 mt-5 space-x-3">
              <button type="button" onClick={() => {onClose()}} className="btn-white">
                {t("common.cancel")}
              </button>
              <button className={(state.errors.length !== 0 || state.errorMessage !== null) ? "btn-disabled" : "btn-green"}
                      disabled={state.errors.length !== 0 || state.errorMessage !== null}
                      type="submit">
                {t("common.save")}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}

AddForm.propTypes = {
  addPath: PropTypes.string.isRequired,
  columns: Columns.isRequired,
  errorStrings: PropTypes.object.isRequired,
  itemKey: PropTypes.string.isRequired,
  jsonSchema: PropTypes.object.isRequired,
  onClose: PropTypes.func.isRequired,
  title: PropTypes.string.isRequired
}

export default AddForm
