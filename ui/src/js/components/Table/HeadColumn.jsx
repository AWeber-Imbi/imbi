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

function HeadColumn({ column, children, className, sort, srOnly }) {
  const [sortDirection, setSortDirection] = useState(sort)

  useEffect(() => {
    if (column.sortCallback !== undefined && sortDirection !== sort) {
      column.sortCallback(column.name, sortDirection)
    }
  }, [sortDirection])

  function onSortClick(event) {
    event.preventDefault()
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

  if (className !== undefined) clsName += ' ' + className
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
      className={
        'align-middle px-6 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap ' +
        clsName
      }>
      {column.sortCallback !== undefined && (
        <button
          className="border-0 mr-2 focus:outline-none"
          onClick={onSortClick}>
          <Icon icon={SortIcon[sortDirection]} />
        </button>
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
  sort: PropTypes.oneOf([null, Asc, Desc]),
  srOnly: PropTypes.bool
}
export { HeadColumn }
