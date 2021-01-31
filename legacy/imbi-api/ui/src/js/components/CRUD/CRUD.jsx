import PropTypes from 'prop-types'
import React, { Fragment, useContext, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Alert, ConfirmationDialog, Icon, Table } from '..'
import { Columns } from '../../schema'
import { FetchContext } from '../../contexts'
import { httpGet, httpDelete } from '../../utils'

import { Form } from './Form'

function CRUD({
  collectionIcon,
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
  const fetchMethod = useContext(FetchContext)

  const [data, setData] = useState([])
  const [errorMessage, setErrorMessage] = useState(null)
  const [fetchData, setFetchData] = useState(true)
  const [itemToDelete, setItemToDelete] = useState(null)
  const [itemToEdit, setItemToEdit] = useState(null)
  const [showDeleteConfirmation, setShowDeleteConfirmation] = useState(false)
  const [showForm, setShowForm] = useState(false)
  const [successMessage, setSuccessMessage] = useState(null)
  const [timerHandle, setTimerHandle] = useState(null)

  const strings = {
    collectionName: collectionName,
    itemName: itemName
  }
  const { t } = useTranslation()

  async function deleteItem() {
    const result = await httpDelete(
      fetchMethod,
      itemPath.replace(/{{value}}/, itemToDelete)
    )
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
  }

  function onDeleteClick(value) {
    setItemToDelete(value)
    setShowDeleteConfirmation(true)
  }

  async function onEditClick(value) {
    httpGet(
      fetchMethod,
      itemPath.replace(/{{value}}/, value),
      (data) => {
        itemIgnore.map((key) => {
          delete data[key]
        })
        setItemToEdit(data)
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

  // Remove the error message after 30 seconds
  useEffect(() => {
    if (errorMessage !== null) {
      if (timerHandle !== null) clearTimeout(timerHandle)
      setTimerHandle(
        setTimeout(() => {
          setErrorMessage(null)
          setTimerHandle(null)
        }, 30000)
      )
    }
  }, [errorMessage])

  // Fetch the collection data
  useEffect(() => {
    if (fetchData === true) {
      setFetchData(false)
      httpGet(
        fetchMethod,
        collectionPath,
        (result) => {
          setData(result)
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
      if (timerHandle !== null) clearTimeout(timerHandle)
      setTimerHandle(
        setTimeout(() => {
          setSuccessMessage(null)
          setTimerHandle(null)
        }, 30000)
      )
    }
  }, [successMessage])

  // Handle unmounting while timer is active
  useEffect(() => {
    if (timerHandle !== null) clearTimeout(timerHandle)
  })

  return (
    <Fragment>
      <div className="grid grid-cols-2 mt-1 mb-3">
        <h1 className="inline-block text-xl text-gray-600 pt-2">
          <Icon icon={collectionIcon} className="ml-2 mr-2" />
          {collectionName}
        </h1>
        <div className="text-right">
          <button
            className="btn-green"
            onClick={() => {
              setShowForm(true)
            }}>
            <Icon className="mr-3" icon="fas plus-circle" />
            {t('admin.crud.newTitle', {
              itemName: itemName,
              ...strings
            })}
          </button>
        </div>
      </div>
      {errorMessage !== null && <Alert level="error">{errorMessage}</Alert>}
      {successMessage !== null && (
        <Alert level="success">{successMessage}</Alert>
      )}
      {showForm === true && (
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
        columns={columns}
        data={data}
        itemKey={itemKey}
        onDeleteClick={onDeleteClick}
        onEditClick={onEditClick}
      />
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
    </Fragment>
  )
}

CRUD.defaultProps = {
  itemIgnore: [],
  omitOnAdd: []
}

CRUD.propTypes = {
  collectionIcon: PropTypes.string.isRequired,
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
  itemTitle: PropTypes.string,
  jsonSchema: PropTypes.object.isRequired,
  omitOnAdd: PropTypes.arrayOf(PropTypes.string)
}

export { CRUD }
