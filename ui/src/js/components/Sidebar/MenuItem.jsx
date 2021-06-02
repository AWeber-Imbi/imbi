import { NavLink } from 'react-router-dom'
import PropTypes from 'prop-types'
import React from 'react'

import { Icon } from '..'

class MenuItem extends React.PureComponent {
  render() {
    return (
      <NavLink className="sidebar-link" to={this.props.to}>
        <div className="inline-block w-6 mr-2 text-center">
          <Icon icon={this.props.icon} />
        </div>
        {this.props.value}
      </NavLink>
    )
  }
}
MenuItem.propTypes = {
  value: PropTypes.string.isRequired,
  to: PropTypes.string.isRequired,
  icon: PropTypes.string.isRequired
}
export { MenuItem }
