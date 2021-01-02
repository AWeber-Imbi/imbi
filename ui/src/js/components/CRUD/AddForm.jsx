import PropTypes from "prop-types"
import React from "react"
import {useTranslation} from "react-i18next";
import {validate} from "jsonschema"

import {Column, Columns} from "./Columns"
import {IconSelect} from "../Forms"

function FormField({autoFocus, ...props}) {
  return (
    <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:items-start sm:pt-5">
      <label htmlFor={"field-" + props.name} className="block text-sm font-medium text-gray-700 sm:mt-px sm:pt-2">
        {props.title}
      </label>
      <div className="mt-1 sm:mt-0 sm:col-span-2">
        {props.type === "icon" && (
          <IconSelect name={props.name}
                      id={"field-" + props.name}
                      placeholder={props.placeholder}
                      autoComplete={props.name}
                      autoFocus={autoFocus}
                      defaultValue={props.default}
                      className="form-input" />
        )}
        {props.type === "select" && (
          <select name={props.name}
                  id={"field-" + props.name}
                  placeholder={props.placeholder}
                  autoComplete={props.name}
                  autoFocus={autoFocus}
                  defaultValue={props.default}
                  className="form-input">
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
          <input type="text"
                 name={props.name}
                 id={"field-" + props.name}
                 autoComplete={props.name}
                 autoFocus={autoFocus}
                 placeholder={props.placeholder}
                 className="form-input"/>
        )}
        {props.type === "textarea" && (
          <textarea name={props.name}
                    id={"field-" + props.name}
                    placeholder={props.placeholder}
                    rows="3"
                    className="form-input"/>
        )}
        {props.description !== undefined && (
          <p className="mt-2 text-sm text-gray-500 col-span-2">{props.description}</p>
        )}
      </div>
    </div>
  )
}

FormField.propTypes = {
  autoFocus: PropTypes.bool.isRequired,
  ...Column
}

function AddForm({title, schema, columns, itemPath, itemTitle, onClose}) {

  console.log(schema)
  const {t} = useTranslation()

  function validateValues(e) {
    e.preventDefault()
    const formData = new FormData(e.target)
    const values = Object.fromEntries(formData)
    console.log(validate(values, schema))
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
          <form onSubmit={validateValues}>
            {columns.map((column, index) => {
              return (<FormField key={"field-" + column.name}
                                 autoFocus={index === 0}
                                 {...column} />)
            })}
            <div className="mt-5 sm:mt-6 text-right border-t border-t-gray-400 pt-5 mt-5 space-x-3">
              <button type="button" onClick={() => {onClose()}} className="btn-white">
                {t("common.cancel")}
              </button>
              <button type="submit" className="btn-green">
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
  title: PropTypes.string.isRequired,
  schema: PropTypes.object.isRequired,
  columns: Columns,
  itemPath: PropTypes.string.isRequired,
  itemTitle: PropTypes.string.isRequired,
  onClose: PropTypes.func.isRequired
}

export default AddForm
