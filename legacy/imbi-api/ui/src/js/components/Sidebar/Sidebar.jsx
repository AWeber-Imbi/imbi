import PropTypes from 'prop-types'
import React from 'react'

import { Section } from './Section'
import { MenuItem } from './MenuItem'

function Sidebar({ title, children }) {
  return (
    <nav className="flex-shrink h-full w-1/6 min-w-max bg-white overflow-y-auto border-r border-gray-200">
      {title && <h1 className="font-gray-600 ml-2 text-lg">{title}</h1>}
      {children}
    </nav>
  )
}
Sidebar.Section = Section
Sidebar.MenuItem = MenuItem
Sidebar.propTypes = {
  title: PropTypes.string,
  children: PropTypes.arrayOf(PropTypes.node)
}
export { Sidebar }
