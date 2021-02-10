import PropTypes from 'prop-types'
import React from 'react'

import { Column as ColumnPropTypes } from '../../schema'
import { Icon } from '..'

function Column({ definition, children }) {
  let clsName =
    definition !== undefined &&
    definition.tableOptions !== undefined &&
    definition.tableOptions.className !== undefined
      ? definition.tableOptions.className
      : ''
  return (
    <td className={'px-5 py-1.5 whitespace-nowrap ' + clsName}>
      {definition !== undefined && definition.type === 'icon' && (
        <Icon className="mr-2" icon={children} title={children} />
      )}
      {definition !== undefined &&
      definition.tableOptions !== undefined &&
      definition.tableOptions.lookupFunction !== undefined
        ? definition.tableOptions.lookupFunction(children)
        : definition.type !== 'icon'
          ? children
          : ''}
    </td>
  )
}

Column.propTypes = {
  definition: PropTypes.exact(ColumnPropTypes),
  children: PropTypes.oneOfType([
    PropTypes.string,
    PropTypes.number,
    PropTypes.element
  ])
}

export { Column }
