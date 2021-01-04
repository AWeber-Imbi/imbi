import PropTypes from "prop-types"
import React from 'react'
import {useTranslation} from "react-i18next";

import {Columns} from "../../schema"

import {Column} from "."

function Row({columns, data, index, onEditClick}) {
  const {t} = useTranslation()
  const toRender = columns.map((column) => {
    if (column.tableOptions === undefined) return column
    if (column.tableOptions.hide !== true) return column
  }).filter(column => column !== undefined)
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
      {onEditClick !== undefined && (
        <Column>
          <button type="button" className="text-center w-full text-blue-700 hover:text-blue:800" onClick={onEditClick}>
            {t("common.edit")}
          </button>
        </Column>)
      }
    </tr>
  )
}
Row.propTypes = {
  columns: Columns.isRequired,
  data: PropTypes.object.isRequired,
  index: PropTypes.number.isRequired,
  onEditClick: PropTypes.func
}

export default Row
