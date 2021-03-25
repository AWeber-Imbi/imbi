import PropTypes from 'prop-types'
import React, { useContext, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import {
  Alert,
  Backdrop,
  ConfirmationDialog,
  ErrorBoundary,
  Icon,
  Loading,
  Table
} from '..'
import { Columns } from '../../schema'
import { Context } from '../../state'
import { httpGet, httpDelete } from '../../utils'

import { Form } from './Form'

function CRUD({
  collectionName,
  collectionPath,
  columns,
  errorStrings,
  itemIgnore,
  itemKey,
  itemName,
  itemPath,
  itemTitle,
  jsonSchema
}) {
  const [state, dispatch] = useContext(Context)
  const [data, setData] = useState([])
  const [errorMessage, setErrorMessage] = useState(null)
  const [fetchData, setFetchData] = useState(true)
  const [fetching, setFetching] = useState(false)
  const [itemToDelete, setItemToDelete] = useState('')
  const [itemToEdit, setItemToEdit] = useState(null)
  const [ready, setReady] = useState(false)
  const [showDeleteConfirmation, setShowDeleteConfirmation] = useState(false)
  const [showForm, setShowForm] = useState(false)
  const [successMessage, setSuccessMessage] = useState(null)
  const strings = {
    collectionName: collectionName,
    itemName: itemName
  }
  const { t } = useTranslation()

  async function deleteItem() {
    const path = itemPath.replace(/{{value}}/, itemToDelete)
    const url = new URL(path, state.baseURL)
    const result = await httpDelete(state.fetch, url)
    if (result.success === true) {
      setSuccessMessage(
        t('admin.crud.itemDeleted', { value: itemToDelete, ...strings })
      )
      setItemToDelete(null)
      setFetchData(true)
    } else {
      setErrorMessage(
        errorStrings[result.data] !== undefined
          ? errorStrings[result.data]
          : result.data
      )
    }
    setShowDeleteConfirmation(false)
    state.refreshMetadata()
  }

  function onDeleteClick(value) {
    setItemToDelete(value)
    setShowDeleteConfirmation(true)
  }

  async function onEditClick(value) {
    setFetching(true)
    const path = itemPath.replace(/{{value}}/, value)
    const url = new URL(path, state.baseURL)
    httpGet(
      state.fetch,
      url,
      (data) => {
        itemIgnore.map((key) => {
          delete data[key]
        })
        setItemToEdit(data)
        setFetching(false)
        setShowForm(true)
      },
      (message) => {
        setErrorMessage(
          errorStrings[message] !== undefined ? errorStrings[message] : message
        )
      }
    )
  }

  function onFormClosed(value) {
    if (value !== undefined) {
      const message =
        itemToEdit === null ? 'admin.crud.itemAdded' : 'admin.crud.itemUpdated'
      setSuccessMessage(t(message, { value: value, ...strings }))
      setFetchData(true)
    }
    setItemToEdit(null)
    setShowForm(false)
  }

  useEffect(() => {
    dispatch({
      type: 'SET_CURRENT_PAGE',
      payload: {
        title: collectionName,
        url: new URL(window.location.pathname, state.baseURL)
      }
    })
  }, [])

  // Remove the error message after 30 seconds
  useEffect(() => {
    if (errorMessage !== null) {
      const timerHandle = setTimeout(() => {
        setErrorMessage(null)
      }, 30000)
      return function cleanup() {
        clearTimeout(timerHandle)
      }
    }
  }, [errorMessage])

  // Fetch the collection data
  useEffect(() => {
    if (fetchData === true) {
      setFetchData(false)
      const url = new URL(collectionPath, state.baseURL)
      httpGet(
        state.fetch,
        url,
        (result) => {
          setData(result)
          setReady(true)
        },
        (error) => {
          setErrorMessage(error)
        }
      )
    }
  }, [fetchData])

  // Remove the success message after 30 seconds
  useEffect(() => {
    if (successMessage !== null) {
      const timerHandle = setTimeout(() => {
        setSuccessMessage(null)
      }, 30000)
      return function cleanup() {
        clearTimeout(timerHandle)
      }
    }
  }, [successMessage])

  if (!ready) return <Loading />
  if (errorMessage !== null)
    return (
      <Alert className="mb-3" level="error">
        {errorMessage}
      </Alert>
    )
  return (
    <ErrorBoundary>
      <div className="space-y-3">
        <div className="text-right">
          <button
            className="btn-green"
            onClick={() => {
              setShowForm(true)
            }}>
            <Icon className="mr-2" icon="fas plus-circle" />
            {t('admin.crud.newTitle', {
              itemName: itemName,
              ...strings
            })}
          </button>
        </div>
        {successMessage !== null && (
          <Alert className="mb-3" level="success">
            {successMessage}
          </Alert>
        )}
        {showForm && (
          <Form
            columns={columns}
            errorStrings={errorStrings}
            isEdit={itemToEdit !== null}
            itemKey={itemKey}
            itemPath={itemToEdit === null ? collectionPath : itemPath}
            itemTitle={itemTitle}
            jsonSchema={jsonSchema}
            onClose={onFormClosed}
            onEditClick={onEditClick}
            savingTitle={t('admin.crud.savingTitle', {
              itemName: itemName
            })}
            title={t(
              itemToEdit === null
                ? 'admin.crud.newTitle'
                : 'admin.crud.updateTitle',
              { itemName: itemName }
            )}
            values={itemToEdit}
          />
        )}
        <Table
          className="my-3"
          columns={columns}
          data={data}
          itemKey={itemKey}
          onDeleteClick={onDeleteClick}
          onEditClick={onEditClick}
        />
        {fetching && <Backdrop wait={true} />}
        {showDeleteConfirmation === true && (
          <ConfirmationDialog
            mode="error"
            title={t('admin.crud.deleteConfirmation.title', {
              value: itemToDelete,
              ...strings
            })}
            confirmationButtonText={t('admin.crud.deleteConfirmation.button', {
              value: itemToDelete,
              ...strings
            })}
            onCancel={() => {
              setItemToDelete(null)
              setShowDeleteConfirmation(null)
            }}
            onConfirm={deleteItem}>
            {t('admin.crud.deleteConfirmation.text', {
              value: itemToDelete,
              ...strings
            })}
          </ConfirmationDialog>
        )}
      </div>
    </ErrorBoundary>
  )
}
CRUD.defaultProps = {
  itemIgnore: [],
  omitOnAdd: []
}
CRUD.propTypes = {
  collectionName: PropTypes.string.isRequired,
  collectionPath: PropTypes.string.isRequired,
  columns: Columns.isRequired,
  errorStrings: PropTypes.object.isRequired,
  itemIgnore: PropTypes.arrayOf(PropTypes.string),
  itemKey: PropTypes.oneOfType([
    PropTypes.string,
    PropTypes.arrayOf(PropTypes.String)
  ]),
  itemName: PropTypes.string.isRequired,
  itemPath: PropTypes.string.isRequired,
  itemTitle: PropTypes.oneOfType([PropTypes.string, PropTypes.func]),
  jsonSchema: PropTypes.object.isRequired,
  omitOnAdd: PropTypes.arrayOf(PropTypes.string)
}
export { CRUD }
