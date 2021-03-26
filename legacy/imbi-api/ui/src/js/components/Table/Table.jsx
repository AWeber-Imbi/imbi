import PropTypes from 'prop-types'
import React from 'react'

import { Columns } from '../../schema'

import { Head, Body, Footer } from '.'

function Table({
  columns,
  data,
  disabled,
  itemKey,
  onDeleteClick,
  onEditClick,
  onRowClick,
  rowURL
}) {
  return (
    <div className="shadow bg-gray-50 overflow-hidden border-b border-gray-200 rounded-lg">
      <table className="bg-gray-50 divide-y divide-gray-200 table-fixed w-full">
        <Head
          columns={columns}
          disabled={disabled}
          includeEdit={onEditClick !== undefined || onDeleteClick !== undefined}
        />
        <Body
          columns={columns}
          data={data}
          disabled={disabled}
          itemKey={itemKey}
          onDeleteClick={onDeleteClick}
          onEditClick={onEditClick}
          onRowClick={onRowClick}
          rowURL={rowURL}
        />
        <Footer
          columns={columns.length + (onEditClick !== undefined ? 1 : 0)}
        />
      </table>
    </div>
  )
}

Table.propTypes = {
  columns: Columns,
  data: PropTypes.arrayOf(PropTypes.object),
  disabled: PropTypes.bool,
  itemKey: PropTypes.string,
  onDeleteClick: PropTypes.func,
  onEditClick: PropTypes.func,
  onRowClick: PropTypes.func,
  rowURL: PropTypes.oneOfType([PropTypes.func, PropTypes.string])
}

export { Table }
