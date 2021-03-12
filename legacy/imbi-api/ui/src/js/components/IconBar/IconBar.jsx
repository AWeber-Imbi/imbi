import PropTypes from 'prop-types'
import React from 'react'

import { Icon, Tooltip } from '..'

function IconBar({ icons }) {
  return (
    <div className="inline-block text-gray-500">
      {icons.map((icon) => {
        if (icon.url !== undefined && icon.url !== null)
          return (
            <Tooltip
              className="ml-1.5"
              key={`icon-${icon.title}`}
              value={icon.title}>
              <a
                href={icon.url}
                className="mr-3 hover:text-blue-700"
                key={`icon-${icon.title}`}
                target="_new">
                <Icon icon={icon.icon} />
              </a>
            </Tooltip>
          )
        return (
          <Tooltip
            className="ml-1.5"
            key={`icon-${icon.title}`}
            value={icon.title}>
            <Icon className="mr-3" icon={icon.icon} />
          </Tooltip>
        )
      })}
    </div>
  )
}

IconBar.propTypes = {
  icons: PropTypes.arrayOf(
    PropTypes.exact({
      link_type_id: PropTypes.number.isRequired,
      icon: PropTypes.string.isRequired,
      title: PropTypes.string,
      url: PropTypes.string
    })
  )
}

export { IconBar }
