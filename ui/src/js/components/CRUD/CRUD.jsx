import PropTypes from "prop-types"
import React, {Fragment, useState} from "react"
import {useTranslation} from "react-i18next";

import {Alert, Icon, Table} from ".."
import {Columns} from "../../schema"
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
               jsonSchema}) {
  const [dataIndex, setDataIndex] = useState(0)
  const [errorMessage, setErrorMessage] = useState(null)
  const [successMessage, setSuccessMessage] = useState(null)
  const [showAddForm, setShowAddForm] = useState(false)
  const {t} = useTranslation()

  const [data, dataErrorMessage] = useFetch(collectionPath, [], false, dataIndex)

  if (dataErrorMessage !== undefined) setErrorMessage(dataErrorMessage)

  function onAddFormClosed(keyValue) {
    setShowAddForm(false)
    if (keyValue !== undefined)
      setSuccessMessage(t("admin.crud.itemAdded", {keyValue: keyValue, collectionName: collectionName}))
    refreshData()
  }

  onAddFormClosed.propTypes = {
    keyValue: PropTypes.string
  }

  function refreshData() {
    setDataIndex(dataIndex + 1)
  }

  function onEditClick(keyValue) {
    console.log('Edit ' + keyValue + ' clicked')
  }

  function onDeleteClick(keyValue) {
    console.log('Delete ' + keyValue + ' clicked')
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
             onDeleteClick={onDeleteClick}
             onEditClick={onEditClick}/>
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
  jsonSchema: PropTypes.object.isRequired
}

export default CRUD
