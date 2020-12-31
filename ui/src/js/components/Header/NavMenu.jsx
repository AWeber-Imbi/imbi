import {FontAwesomeIcon} from "@fortawesome/react-fontawesome";
import {faWrench} from '@fortawesome/free-solid-svg-icons'
import {Link} from '@reach/router'
import {Menu} from '@headlessui/react'
import React from 'react'
import PropTypes from "prop-types"

import {Tooltip} from '../'
import {User} from '../../schema'

function MenuItem({children, to}) {
  const itemClass = {
    true: 'bg-blue-600 px-3 py-2 rounded-md ',
    false: 'hover:bg-blue-600 hover:text-white px-3 py-2 rounded-md'
  }
  return (
    <Link getProps={({isCurrent}) => {return {className: itemClass[isCurrent]}}}
          key={to.replace(/\//gi, '_') + '-nav-item'}
          to={to}>
      {children}
    </Link>
  )
}

MenuItem.propTypes = {
  children: PropTypes.oneOfType([PropTypes.string, PropTypes.object]).isRequired,
  to: PropTypes.string.isRequired
}

function NavMenu({currentUser}) {
  if (currentUser.authenticated === true)
  return (
    <Menu as="div" className="flex-grow ml-2 mt-2 space-x-2 font-medium text-sm text-white">
      <MenuItem to="/ui/">Dashboard</MenuItem>
      <MenuItem to="/ui/projects">Projects</MenuItem>
      {currentUser.permissions.includes('admin') && (
        <Tooltip value="Admin Tools">
          <MenuItem to="/ui/admin">
            <FontAwesomeIcon icon={faWrench} className="p-0 m-0"/>
          </MenuItem>
        </Tooltip>
      )}
    </Menu>)
  return null
}

NavMenu.propTypes = {
  currentUser: PropTypes.shape(User)
}

export default NavMenu
