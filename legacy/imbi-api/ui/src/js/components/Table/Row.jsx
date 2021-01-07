import PropTypes from "prop-types"
import React, {Fragment} from 'react'
import {useTranslation} from "react-i18next";

import {Columns} from "../../schema"

import {Column} from "."

function Row({columns, data, index, itemKey, onDeleteClick, onEditClick}) {
  const {t} = useTranslation()
  const toRender = columns.map((column) => {
    if (column.tableOptions === undefined) return column
    if (column.tableOptions.hide !== true) return column
  }).filter(column => column !== undefined)

  function deleteOnCick(e) {
    e.preventDefault()
    onDeleteClick(data[itemKey])
  }

  function editOnCick(e) {
    e.preventDefault()
    onEditClick(data[itemKey])
  }

  let colOffset = -1
  return (
    <tr className={"hover:bg-gray-100"}>
      {toRender.map((column) => {
        colOffset += 1
        return (
          <Column definition={column}
                  key={'table-row-' + index + '-col-' + colOffset}>
            {data[column.name]}
          </Column>
        )
      })}
      {(onEditClick !== undefined || onDeleteClick !== undefined) && (
        <Column>
          <Fragment>
            {onEditClick !== undefined && (
              <button type="button" className="text-center text-gray-400 hover:text-blue-700 focus:outline-none" onClick={editOnCick}>
                {t("common.edit")}
              </button>
            )}
            {(onEditClick !== undefined && onDeleteClick !== undefined) && (
              <span className="mx-2">&ndash;</span>
            )}
            {onDeleteClick !== undefined && (
              <button type="button" className="text-center text-gray-400 hover:text-red-700 focus:outline-none" onClick={deleteOnCick}>
                {t("common.delete")}
              </button>
            )}
          </Fragment>
        </Column>
      )}
    </tr>
  )
}
Row.propTypes = {
  columns: Columns.isRequired,
  data: PropTypes.object.isRequired,
  index: PropTypes.number.isRequired,
  itemKey: PropTypes.string,
  onDeleteClick: PropTypes.func,
  onEditClick: PropTypes.func
}

export {Row}
