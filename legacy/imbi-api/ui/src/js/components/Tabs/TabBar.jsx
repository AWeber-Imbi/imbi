import PropTypes from 'prop-types'
import React from 'react'

import { Tab } from './Tab'

function TabBar({ children }) {
  return (
    <div className="border-b border-gray-200 mb-4">
      <nav className="-mb-px flex space-x-8" aria-label="Tabs">
        {children}
      </nav>
    </div>
  )
}
TabBar.propTypes = {
  children: PropTypes.arrayOf(Tab)
}
export { TabBar }
