import PropTypes from "prop-types"
import React from 'react'

import {Columns} from "../../schema"

import {Head, Body, Footer} from "."

function Table({columns, data, onEditClick}) {
  return (
    <div className="py-3 align-middle">
      <div className="shadow overflow-hidden border-b border-gray-200 sm:rounded-lg">
        <table className="min-w-full divide-y divide-gray-200">
          <Head columns={columns} includeEdit={onEditClick !== undefined}/>
          <Body columns={columns} data={data} onEditClick={onEditClick}/>
          <Footer columns={columns.length + (onEditClick !== undefined ? 1 : 0)}/>
        </table>
      </div>
    </div>
  )
}

Table.propTypes = {
  columns: Columns,
  data: PropTypes.arrayOf(PropTypes.object),
  onEditClick: PropTypes.func
}

export default Table
