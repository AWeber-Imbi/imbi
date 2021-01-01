import {FontAwesomeIcon} from "@fortawesome/react-fontawesome";
import {faCaretDown, faPlusSquare} from '@fortawesome/free-solid-svg-icons'
import {Link} from '@reach/router'
import {Menu} from '@headlessui/react'
import React from 'react'
import PropTypes from "prop-types"

import {User} from '../../schema'

const menuClasses = 'block px-4 py-2 text-gray-600 hover:bg-gray-100 hover:text-blue-700 focus:outline-none text-sm'

function NewMenuItem({value, to}) {
  const itemClass = {
    true: menuClasses + ' font-bold',
    false: menuClasses
  }
  return (
    <Menu.Item>
      <Link getProps={({isCurrent}) => {return {className: itemClass[isCurrent]}}}
            key={to.replace(/\//gi, '_') + '-nav-item'}
            to={to}>
        {value}
      </Link>
    </Menu.Item>
  )
}

NewMenuItem.propTypes = {
  value: PropTypes.string.isRequired,
  to: PropTypes.string.isRequired
}

function UserMenu({currentUser}) {
  if (currentUser.authenticated === true)
    return (
      <Menu as="div" className="flex-shrink mr-3">
        <Menu.Button as="button"
                     className="bg-blue-700 hover:bg-blue-600 border border-blue-200 text-white hover:text-white px-3 py-1.5 rounded-md mr-5">
          <FontAwesomeIcon icon={faPlusSquare}/>
          <FontAwesomeIcon icon={faCaretDown} className="ml-3"/>
        </Menu.Button>
        <Menu.Items aria-labelledby="user-menu"
                    aria-orientation="vertical"
                    className="origin-top-right absolute right-20 mt-1 w-48 rounded-md shadow-lg py-1 focus:outline-none bg-white ring-1 ring-gray-300 ring-opacity-5">
          <NewMenuItem to='/ui/changelog#new' value="New Change Log Entry"/>
          <NewMenuItem to='/ui/project#new' value="New Project"/>
        </Menu.Items>
      </Menu>
    )
  return null
}

UserMenu.propTypes = {
  currentUser: PropTypes.shape(User)
}

export default UserMenu
