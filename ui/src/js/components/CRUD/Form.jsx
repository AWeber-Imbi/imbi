import { compare } from 'fast-json-patch'
import PropTypes from 'prop-types'
import React, { useContext, useState } from 'react'

import { Columns } from '../../schema'
import { Form } from '..'
import { httpPost, httpPatch, isFunction } from '../../utils'
import { Context } from '../../state'

function CrudForm({
  columns,
  errorStrings,
  isEdit,
  itemKey,
  itemPath,
  itemTitle,
  jsonSchema,
  onClose,
  savingTitle,
  title,
  values
}) {
  const [state] = useContext(Context)
  const [originalValues, _] = useState(values) // eslint-disable-line

  async function handleSubmit(formValues) {
    const url = new URL(state.baseURL)
    let result = null
    if (isEdit === true) {
      const patchValue = compare(originalValues, formValues)
      url.pathname = itemPath.replace(/{{value}}/, originalValues[itemKey])
      result = await httpPatch(state.fetch, url, patchValue)
    } else {
      url.pathname = itemPath
      result = await httpPost(state.fetch, url, formValues)
    }
    if (result.success === true) {
      state.refreshMetadata()
      if (isFunction(itemTitle)) onClose(itemTitle(formValues))
      else onClose(formValues[itemTitle !== undefined ? itemTitle : itemKey])
    } else {
      return errorStrings[result.data] !== undefined
        ? errorStrings[result.data]
        : result.data
    }
  }

  return (
    <Form.ModalForm
      columns={columns}
      formType={isEdit === true ? 'edit' : 'add'}
      jsonSchema={jsonSchema}
      onClose={onClose}
      onSubmit={handleSubmit}
      savingTitle={savingTitle}
      title={title}
      values={values}
    />
  )
}

CrudForm.propTypes = {
  columns: Columns.isRequired,
  errorStrings: PropTypes.object.isRequired,
  isEdit: PropTypes.bool.isRequired,
  itemKey: PropTypes.oneOfType([
    PropTypes.string,
    PropTypes.arrayOf(PropTypes.String)
  ]).isRequired,
  itemPath: PropTypes.string.isRequired,
  itemTitle: PropTypes.oneOfType([PropTypes.string, PropTypes.func]),
  jsonSchema: PropTypes.object.isRequired,
  onClose: PropTypes.func.isRequired,
  savingTitle: PropTypes.string.isRequired,
  title: PropTypes.string.isRequired,
  values: PropTypes.object
}

export { CrudForm as Form }
