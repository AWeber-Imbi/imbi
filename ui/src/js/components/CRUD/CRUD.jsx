import PropTypes from "prop-types"
import React, {Fragment, useContext, useState} from "react"
import {useTranslation} from "react-i18next";

import {Alert, ConfirmationDialog, Icon, Table} from ".."
import {Columns} from "../../schema"
import {FetchContext} from "../../contexts"
import {httpDelete} from "../../utils"
import {useFetch} from "../../hooks"

import {default as AddForm} from "./AddForm"


function CRUD({addPath,
               collectionIcon,
               collectionName,
               collectionPath,
               columns,
               errorStrings,
               itemKey,
               itemName,
               itemPath,
               jsonSchema}) {
  const fetchMethod = useContext(FetchContext)

  const [dataIndex, setDataIndex] = useState(0)
  const [errorMessage, setErrorMessage] = useState(null)
  const [itemToDelete, setItemToDelete] = useState(null)
  const [successMessage, setSuccessMessage] = useState(null)
  const [showAddForm, setShowAddForm] = useState(false)
  const [showDeleteConfirmation, setShowDeleteConfirmation] = useState(false)

  const strings = {
    collectionName: collectionName,
    itemName: itemName
  }

  const {t} = useTranslation()

  const [data, dataErrorMessage] = useFetch(collectionPath, [], false, dataIndex)

  if (dataErrorMessage !== undefined) setErrorMessage(dataErrorMessage)

  function onAddFormClosed(keyValue) {
    setShowAddForm(false)
    if (keyValue !== undefined)
      setSuccessMessage(t("admin.crud.itemAdded", {value: keyValue, ...strings}))
    refreshData()
  }

  onAddFormClosed.propTypes = {
    keyValue: PropTypes.string
  }

  async function deleteItem(e) {
    e.preventDefault
    e.target.disabled = true
    const result = await httpDelete(
      fetchMethod,
      itemPath.replace(/{{value}}/, itemToDelete)
    )
    if (result.success === true) {
      setSuccessMessage(t("admin.crud.itemDeleted", {value: itemToDelete, ...strings}))
      refreshData()
    } else {
      setErrorMessage(result.data)
    }
    setItemToDelete(null)
    setShowDeleteConfirmation(false)
  }

  function refreshData() {
    setDataIndex(dataIndex + 1)
  }

  function onEditClick(keyValue) {
    console.log("Edit clicked", keyValue)
  }

  function onDeleteClick(keyValue) {
    setItemToDelete(keyValue)
    setShowDeleteConfirmation(true)
  }

  return (
    <Fragment>
      <div className="grid grid-cols-2 mb-3">
        <h1 className="inline-block text-xl pt-2">
          <Icon icon={collectionIcon} className="mr-2"/>
          {collectionName}
        </h1>
        <div className="text-right">
          <button className="btn-green" onClick={() => {
            setShowAddForm(true)
          }}>
            <Icon className="mr-3" icon="fas plus-circle"/>
            {t("admin.crud.newAction", {itemName: itemName})}
          </button>
        </div>
      </div>
      {errorMessage !== null && (
        <Alert className="my-3" level="success">{successMessage}</Alert>
      )}
      {successMessage !== null && (
        <Alert className="my-3" level="success">{successMessage}</Alert>
      )}
      {showAddForm === true && (
        <AddForm addPath={addPath}
                 columns={columns}
                 errorStrings={errorStrings}
                 itemKey={itemKey}
                 jsonSchema={jsonSchema}
                 onClose={onAddFormClosed}
                 onEditClick={onEditClick}
                 title={t("admin.crud.newAction", {itemName: itemName})}/>
      )}
      <Table columns={columns}
             data={data !== undefined ? data : []}
             itemKey={itemKey}
             onDeleteClick={onDeleteClick}
             onEditClick={onEditClick}/>
      {showDeleteConfirmation === true && (
        <ConfirmationDialog mode="error"
                            title={t("admin.crud.deleteConfirmation.title", {value: itemToDelete, ...strings})}
                            confirmationButtonText={t("admin.crud.deleteConfirmation.button", {value: itemToDelete, ...strings})}
                            onCancel={() => {
                              setItemToDelete(null)
                              setShowDeleteConfirmation(false)
                            }}
                            onConfirm={deleteItem}>
          {t("admin.crud.deleteConfirmation.text", {value: itemToDelete, ...strings})}
        </ConfirmationDialog>
      )}
    </Fragment>
  )
}

CRUD.propTypes = {
  addPath: PropTypes.string.isRequired,
  collectionIcon: PropTypes.string.isRequired,
  collectionName: PropTypes.string.isRequired,
  collectionPath: PropTypes.string.isRequired,
  columns: Columns.isRequired,
  errorStrings: PropTypes.object.isRequired,
  itemKey: PropTypes.oneOfType([PropTypes.string, PropTypes.arrayOf(PropTypes.String)]),
  itemName: PropTypes.string.isRequired,
  itemPath: PropTypes.string.isRequired,
  jsonSchema: PropTypes.object.isRequired
}

export default CRUD
