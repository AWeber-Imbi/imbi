import PropTypes from "prop-types"
import React, {Fragment, useState} from "react"

import {default as AddForm} from "./AddForm"
import {Columns} from "./Columns"
import {Icon} from ".."

function CRUD({addButton, schema, columns, errorStrings, itemPath, itemsPath, itemTitle, itemsTitle, keyField}) {
  const [state, setState] = useState({showAddForm: false})
  return (
    <Fragment>
      <div className="text-right">
        <button className="btn-green"
                onClick={() => {setState({...state, showAddForm: true})}}>
          <Icon className="mr-3" icon="fas plus-circle"/>
          {addButton}
        </button>
      </div>
      {state.showAddForm === true && (
        <AddForm title={addButton}
                 schema={schema}
                 columns={columns}
                 itemPath={itemPath}
                 itemTitle={itemTitle}
                 onClose={() => {setState({...state, showAddForm: false})}}/>
      )}
    </Fragment>
  )
}

CRUD.propTypes = {
  addButton: PropTypes.string.isRequired,
  schema: PropTypes.object,
  columns: Columns,
  itemPath: PropTypes.string.isRequired,
  itemsPath: PropTypes.string.isRequired,
  itemTitle: PropTypes.string.isRequired,
  itemsTitle: PropTypes.string.isRequired,
  keyField: PropTypes.string.isRequired
}

export default CRUD
