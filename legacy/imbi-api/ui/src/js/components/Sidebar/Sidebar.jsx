import PropTypes from 'prop-types'
import React from 'react'

import { Section } from './Section'
import { MenuItem } from './MenuItem'

function Sidebar({ title, children }) {
  return (
    <nav className="flex-shrink h-full w-72 bg-white overflow-y-auto border-r border-gray-200 py-4 px-2">
      <h1 className="font-gray-600 ml-2 text-lg">{title}</h1>
      {children}
    </nav>
  )
}

Sidebar.Section = Section
Sidebar.MenuItem = MenuItem

Sidebar.propTypes = {
  title: PropTypes.string.isRequired,
  children: PropTypes.arrayOf(PropTypes.node)
}

export { Sidebar }
