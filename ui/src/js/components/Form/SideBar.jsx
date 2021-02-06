import PropTypes from 'prop-types'
import React from 'react'

function SideBar({ links }) {
  return (
    <ol className="list-decimal list-inside ml-4 text-gray-500 whitespace-nowrap">
      {links.map((link) => {
        return (
          <li className="mb-2" key={'link-' + link.label}>
            <a className="text-gray-600 hover:text-blue-600" href={link.href}>
              {link.label}
            </a>
          </li>
        )
      })}
    </ol>
  )
}
SideBar.defaultProps = {
  links: []
}
SideBar.propTypes = {
  links: PropTypes.arrayOf(
    PropTypes.exact({
      href: PropTypes.string.isRequired,
      label: PropTypes.string.isRequired
    })
  )
}
export { SideBar }
