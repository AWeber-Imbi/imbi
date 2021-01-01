import {FontAwesomeIcon} from "@fortawesome/react-fontawesome";
import {faUserCog, faIdCard, faSignOutAlt} from '@fortawesome/free-solid-svg-icons'
import Gravatar from 'react-gravatar'
import {Link} from '@reach/router'
import {Menu} from '@headlessui/react'
import React from 'react'
import PropTypes from "prop-types"

import {User} from '../../schema'

const menuClasses = 'block px-4 py-2 text-gray-600 hover:bg-gray-100 hover:text-blue-700 focus:outline-none text-sm'

function MenuItem({value, to, icon}) {
  const itemClass = {
    true: menuClasses + ' font-bold',
    false: menuClasses
  }
  return (
    <Menu.Item>
      <Link getProps={({isCurrent}) => { return {className: itemClass[isCurrent]}}}
            key={to.replace(/\//gi, '_') + '-nav-item'}
            to={to}>
        <div className="inline-block w-6 mr-2 text-center">
          <FontAwesomeIcon icon={icon} />
        </div>
        {value}
      </Link>
    </Menu.Item>
  )
}

MenuItem.propTypes = {
  value: PropTypes.string.isRequired,
  to: PropTypes.string.isRequired,
  icon: PropTypes.object.isRequired
}

function UserMenu({currentUser}) {
  if (currentUser.authenticated === true)
    return (
      <Menu as="div" className="flex-shrink mr-3">
        <Menu.Button as={React.Fragment}>
          <button className="bg-gray-800 flex my-1 text-sm rounded-full focus:outline-none" title="User Menu">
            <span className="sr-only">Open user menu</span>
            <Gravatar className="h-8 w-8 rounded-full"
                      default="mp"
                      email={currentUser.email_address}
                      size={22}/>
          </button>
        </Menu.Button>
        <Menu.Items aria-labelledby="user-menu"
                    aria-orientation="vertical"
                    className="origin-top-right absolute right-3 mt-1 w-48 rounded-md shadow-lg py-1 focus:outline-none bg-white ring-1 ring-gray-300 ring-opacity-5">
          <MenuItem to='/ui/user/profile' icon={faIdCard} value="Profile" />
          <MenuItem to='/ui/user/settings' icon={faUserCog} value="Settings" />
          <Menu.Item>
              <a className={menuClasses} href="/ui/logout">
                <div className="inline-block w-6 mr-2 text-center">
                  <FontAwesomeIcon icon={faSignOutAlt} />
                </div>
                Sign Out
              </a>
          </Menu.Item>
        </Menu.Items>
      </Menu>
    )
  return null
}

UserMenu.propTypes = {
  currentUser: PropTypes.shape(User)
}

export default UserMenu
