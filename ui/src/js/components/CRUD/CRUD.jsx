import PropTypes from "prop-types"
import React, {Fragment, useContext, useEffect, useState} from "react"
import {useTranslation} from "react-i18next";

import {Alert, ConfirmationDialog, Icon, Table} from ".."
import {Columns} from "../../schema"
import {FetchContext} from "../../contexts"
import {httpGet, httpDelete} from "../../utils"

import {default as Form} from "./Form"

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

  const [state, setState] = useState({
    data: [],
    errorMessage: null,
    fetchData: true,
    itemToDelete: null,
    itemToEdit: null,
    refreshData: false,
    showDeleteConfirmation: false,
    showForm: false,
    successMessage: null
  })

  const strings = {
    collectionName: collectionName,
    itemName: itemName
  }
  const {t} = useTranslation()

  async function deleteItem() {
    const result = await httpDelete(
      fetchMethod,
      itemPath.replace(/{{value}}/, state.itemToDelete)
    )

    const newState = {
      ...state,
      fetchData: true,
      itemToDelete: null,
      showDeleteConfirmation: false
    }

    if (result.success === true) {
      newState.successMessage = t("admin.crud.itemDeleted",
                                  {value: state.itemToDelete, ...strings})
    } else {
      newState.errorMessage = result.data
    }
    setState(newState)
  }

  function onDeleteClick(value) {
    setState({
      ...state,
      fetchData: true,
      itemToDelete: value,
      showDeleteConfirmation: true
    })
  }

  async function onEditClick(value) {
    httpGet(
      fetchMethod,
      itemPath.replace(/{{value}}/, value),
      (data) => {
        setState({
          ...state,
          itemToEdit: data,
          showForm: true})
      },
      (message) => {
        setState({
          ...state,
          errorMessage: message})
      }
    )
  }

  function onFormClosed(value) {
    const newState = {
      ...state,
      itemToEdit: null,
      showForm: false
    }
    if (value !== undefined) {
      const message = state.itemToEdit === null
                      ? "admin.crud.itemAdded"
                      : "admin.crud.itemUpdated"
      newState.successMessage = t(message, {value: value, ...strings})
      newState.fetchData = true
    }
    setState(newState)
  }

  useEffect(() => {
    if (state.fetchData === true) {
      httpGet(fetchMethod,
              collectionPath,
              (result) => {
                setState({...state, fetchData: false, data: result})
              },
              (error) => {
                setState({...state, fetchData: false, errorMessage: error})
              })
    }
  }, [state.fetchData])


  // Remove the error message after 30 seconds
  useEffect(() => {
    if (state.errorMessage !== null) {
      setTimeout(() => {
        setState({...state, errorMessage: null})
      }, 30000)
    }
  }, [state.errorMessage])

  // Remove the success message after 30 seconds
  useEffect(() => {
    if (state.successMessage !== null) {
      setTimeout(() => {
        setState({...state, successMessage: null})
      }, 30000)
    }
  }, [state.successMessage])

  return (
    <Fragment>
      <div className="grid grid-cols-2 mb-3">
        <h1 className="inline-block text-xl pt-2">
          <Icon icon={collectionIcon} className="mr-2"/>
          {collectionName}
        </h1>
        <div className="text-right">
          <button className="btn-green" onClick={() => {
            setState({...state, showForm: true})
          }}>
            <Icon className="mr-3" icon="fas plus-circle"/>
            {t("admin.crud.newTitle", {itemName: itemName, ...strings})}
          </button>
        </div>
      </div>
      {state.errorMessage !== null && (
        <Alert level="success">{state.errorMessage}</Alert>
      )}
      {state.successMessage !== null && (
        <Alert level="success">{state.successMessage}</Alert>
      )}
      {state.showForm === true && (
        <Form columns={columns}
              errorStrings={errorStrings}
              isEdit={state.itemToEdit !== null}
              itemKey={itemKey}
              itemPath={state.itemToEdit === null ? addPath : itemPath}
              jsonSchema={jsonSchema}
              onClose={onFormClosed}
              onEditClick={onEditClick}
              savingTitle={t("admin.crud.savingTitle", {itemName: itemName})}
              title={t(state.itemToEdit === null ? "admin.crud.newTitle" : "admin.crud.updateTitle",
                       {itemName: itemName})}
              values={state.itemToEdit}/>
      )}
      <Table columns={columns}
             data={state.data}
             itemKey={itemKey}
             onDeleteClick={onDeleteClick}
             onEditClick={onEditClick}/>
      {state.showDeleteConfirmation === true && (
        <ConfirmationDialog mode="error"
                            title={t("admin.crud.deleteConfirmation.title",
                                     {value: state.itemToDelete, ...strings})}
                            confirmationButtonText={t("admin.crud.deleteConfirmation.button",
                                                      {value: state.itemToDelete, ...strings})}
                            onCancel={() => {
                              setState({
                                ...state,
                                itemToDelete: null,
                                showDeleteConfirmation: false})
                            }}
                            onConfirm={deleteItem}>
          {t("admin.crud.deleteConfirmation.text",
             {value: state.itemToDelete, ...strings})}
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
  itemKey: PropTypes.oneOfType([
    PropTypes.string,
    PropTypes.arrayOf(PropTypes.String)
  ]),
  itemName: PropTypes.string.isRequired,
  itemPath: PropTypes.string.isRequired,
  jsonSchema: PropTypes.object.isRequired
}

export default CRUD
