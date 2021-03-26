import PropTypes from 'prop-types'
import React, { useEffect, useState } from 'react'

import { Column } from '../../schema'
import { Icon } from '../'

const Asc = 'asc'
const Desc = 'desc'

const SortIcon = {
  null: 'fas sort',
  asc: 'fas sort-up',
  desc: 'fas sort-down'
}

const ColClassName =
  'align-middle px-6 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap'

function HeadColumn({ column, children, className, disabled, srOnly }) {
  const [sortDirection, setSortDirection] = useState(column.sortDirection)
  useEffect(() => {
    if (
      column.sortCallback !== undefined &&
      sortDirection !== column.sortDirection
    ) {
      column.sortCallback(column.name, sortDirection)
    }
  }, [sortDirection])

  function onSortClick(event) {
    event.preventDefault()
    if (disabled) return
    if (sortDirection === null) {
      setSortDirection(Asc)
    } else if (sortDirection === Asc) {
      setSortDirection(Desc)
    } else if (sortDirection === Desc) {
      setSortDirection(null)
    }
  }

  let clsName =
    column.tableOptions !== undefined &&
    column.tableOptions.headerClassName !== undefined
      ? column.tableOptions.headerClassName
      : ''

  if (className !== undefined) clsName = `${clsName} ${className}`
  clsName = `${clsName} ${
    column.sortCallback !== undefined ? 'cursor-pointer' : ''
  }`
  if (disabled) clsName = `${clsName} disabled cursor-wait`

  if (srOnly === true) {
    return (
      <th scope="col" className={'relative px-6 py-2 ' + clsName}>
        <span className="sr-only">
          {children !== undefined && children}
          {column.title !== undefined && column.title}
        </span>
      </th>
    )
  }
  return (
    <th
      scope="col"
      className={`${ColClassName} ${clsName}`}
      onClick={onSortClick}>
      {column.sortCallback !== undefined && (
        <Icon
          icon={SortIcon[sortDirection]}
          className={`mr-2 ${sortDirection !== null ? 'text-blue-600' : ''}`}
        />
      )}
      {children !== undefined && children}
      {column.title !== undefined && column.title}
    </th>
  )
}
HeadColumn.defaultProps = {
  column: { name: 'default', title: 'default', type: 'text' },
  sort: null,
  srOnly: false
}
HeadColumn.propTypes = {
  column: PropTypes.exact(Column),
  children: PropTypes.string,
  className: PropTypes.string,
  disabled: PropTypes.bool,
  srOnly: PropTypes.bool
}
export { HeadColumn }
