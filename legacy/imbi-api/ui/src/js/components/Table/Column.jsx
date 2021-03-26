import { Link } from 'react-router-dom'
import PropTypes from 'prop-types'
import React from 'react'

import { Column as ColumnPropTypes } from '../../schema'
import { Icon } from '..'

function Column({ definition, children, linkTo }) {
  let clsName = ''
  let value = children
  if (definition !== undefined && definition.tableOptions !== undefined) {
    if (definition.type === 'icon') value = ''
    if (definition.tableOptions.className !== undefined)
      clsName = definition.tableOptions.className
    if (definition.tableOptions.lookupFunction !== undefined)
      value = definition.tableOptions.lookupFunction(children)
  }
  if (linkTo !== undefined)
    return (
      <td>
        <Link
          className={`align-middle h-full inline-block px-5 py-1.5 w-full whitespace-nowrap ${clsName}`}
          to={linkTo}>
          {definition !== undefined && definition.type === 'icon' && (
            <Icon className="mr-2" icon={children} title={children} />
          )}
          {value}
        </Link>
      </td>
    )
  return (
    <td className={`px-5 py-1.5 whitespace-nowrap ${clsName}`}>
      {definition !== undefined && definition.type === 'icon' && (
        <Icon className="mr-2" icon={children} title={children} />
      )}
      {value}
    </td>
  )
}
Column.propTypes = {
  definition: PropTypes.exact(ColumnPropTypes),
  children: PropTypes.oneOfType([
    PropTypes.element,
    PropTypes.number,
    PropTypes.string,
    PropTypes.arrayOf(PropTypes.element),
    PropTypes.arrayOf(PropTypes.number),
    PropTypes.arrayOf(PropTypes.string)
  ]),
  linkTo: PropTypes.string
}
export { Column }
