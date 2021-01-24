import PropTypes from 'prop-types'
import React from 'react'

import { Columns } from '../../schema'

import { Head, Body, Footer } from '.'

function Table({ columns, data, itemKey, onDeleteClick, onEditClick }) {
  return (
    <table className="bg-gray-50 border-b border-gray-200 divide-y divide-gray-200 mt-3 table-fixed w-full shadow">
      <Head
        columns={columns}
        includeEdit={onEditClick !== undefined || onDeleteClick !== undefined}
      />
      <Body
        columns={columns}
        data={data}
        itemKey={itemKey}
        onDeleteClick={onDeleteClick}
        onEditClick={onEditClick}
      />
      <Footer columns={columns.length + (onEditClick !== undefined ? 1 : 0)} />
    </table>
  )
}

Table.propTypes = {
  columns: Columns,
  data: PropTypes.arrayOf(PropTypes.object),
  itemKey: PropTypes.string,
  onDeleteClick: PropTypes.func,
  onEditClick: PropTypes.func
}

export { Table }
