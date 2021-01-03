import PropTypes from "prop-types"
import React, {Fragment, useState} from "react"
import {useTranslation} from "react-i18next";

import {default as AddForm} from "./AddForm"
import {Columns} from "./Columns"
import {Alert, Icon} from ".."

function CRUD({addPath, collectionName, collectionPath, columns, errorStrings, itemKey, itemName, jsonSchema}) {
  const [state, setState] = useState({showAddForm: false, successMessage: null})
  const {t} = useTranslation()

  function onAddFormClosed(keyValue) {
    setState({...state,
      showAddForm: false,
      successMessage: keyValue !== undefined
        ? t("admin.crud.itemAdded", {keyValue: keyValue, collectionName: collectionName})
        : null
    })
  }
  onAddFormClosed.propTypes = {
    keyValue: PropTypes.string
  }
  return (
    <Fragment>
      <div className="text-right">
        <button className="btn-green"
                onClick={() => {setState({...state, showAddForm: true})}}>
          <Icon className="mr-3" icon="fas plus-circle"/>
          {t("admin.crud.newAction", {itemName: itemName})}
        </button>
      </div>
      {state.successMessage !== null && (
        <Alert className="my-3" level="success">{state.successMessage}</Alert>
      )}
      {state.showAddForm === true && (
        <AddForm addPath={addPath}
                 columns={columns}
                 errorStrings={errorStrings}
                 itemKey={itemKey}
                 jsonSchema={jsonSchema}
                 onClose={onAddFormClosed}
                 title={t("admin.crud.newAction", {itemName: itemName})}/>
      )}
    </Fragment>
  )
}

CRUD.propTypes = {
  addPath: PropTypes.string.isRequired,
  collectionName: PropTypes.string.isRequired,
  collectionPath: PropTypes.string.isRequired,
  columns: Columns.isRequired,
  errorStrings: PropTypes.object.isRequired,
  itemKey: PropTypes.oneOfType([PropTypes.string, PropTypes.arrayOf(PropTypes.String)]),
  itemName: PropTypes.string.isRequired,
  jsonSchema: PropTypes.object.isRequired
}

export default CRUD
