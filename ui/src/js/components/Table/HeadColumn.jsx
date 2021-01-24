import PropTypes from 'prop-types'
import React from 'react'

import { Column } from '../../schema'

function HeadColumn({ column, children, className, srOnly }) {
  let clsName =
    column !== undefined &&
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
          {column !== undefined && column.title}
        </span>
      </th>
    )
  }
  return (
    <th
      scope="col"
      className={
        'px-6 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider ' +
        clsName
      }>
      {children !== undefined && children}
      {column !== undefined && column.title}
    </th>
  )
}

HeadColumn.defaultProps = {
  srOnly: false
}

HeadColumn.propTypes = {
  column: PropTypes.exact(Column),
  children: PropTypes.string,
  className: PropTypes.string,
  srOnly: PropTypes.bool
}

export { HeadColumn }
