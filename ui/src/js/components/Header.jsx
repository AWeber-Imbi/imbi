import {FontAwesomeIcon} from "@fortawesome/react-fontawesome";
import {faWrench} from '@fortawesome/free-solid-svg-icons'
import Gravatar from 'react-gravatar'
import {Link} from '@reach/router'
import {Menu} from '@headlessui/react'
import React, {useContext} from 'react'
import PropTypes from "prop-types"

import {Hamburger, Tooltip} from '.'
import {UserContext} from '../contexts'

function NavMenuItem({children, to}) {
  const itemClass = {
    true: 'bg-blue-900 text-white px-3 py-2 rounded-md text-sm font-medium',
    false: 'text-blue-300 hover:bg-blue-800 hover:text-white px-3 py-2 rounded-md text-sm font-medium'
  }
  return (
    <Link getProps={({isCurrent}) => {return {className: itemClass[isCurrent]}}}
          key={to.replace(/\//gi, '_') + '-nav-item'}
          to={to}>
      {children}
    </Link>
  )
}

NavMenuItem.propTypes = {
  children: PropTypes.oneOfType([PropTypes.string, PropTypes.object]).isRequired,
  to: PropTypes.string.isRequired
}

function UserMenuItem({children, to}) {
  const itemClass = {
    true: 'user-menu-link-active',
    false: 'user-menu-link'
  }
  return (
    <Menu.Item>
      <Link getProps={({isCurrent}) => {return {className: itemClass[isCurrent]}}}
            key={to.replace(/\//gi, '_') + '-nav-item'}
            to={to}>
        {children}
      </Link>
    </Menu.Item>
  )
}

UserMenuItem.propTypes = {
  children: PropTypes.string.isRequired,
  to: PropTypes.string.isRequired
}

function Header({logo, service}) {
  const currentUser = useContext(UserContext)
  return (
    <header>
      <nav className="bg-blue-700 border-b-2 border-blue-900">
        <div className="mx-auto px-2 sm:px-4 lg:px-6">
          <div className="relative flex items-center justify-between h-16">
            {currentUser.authenticated === true && (<Hamburger/>)}
            <div className="flex-1 flex items-center justify-center sm:items-stretch sm:justify-start">
              <div className="flex-shrink-0 flex items-center">
                <img className="block lg:hidden h-8 w-8" src={logo} alt={service}/>
                <img className="hidden lg:block h-8 w-8" src={logo} alt={service}/>
                {currentUser.authenticated === true && (
                  <h1 className="inline-block sm:hidden text-xl ml-2 text-white">{service}</h1>)}
                {currentUser.authenticated !== true && (
                  <h1 className="inline-block text-xl ml-2 text-white">{service}</h1>)}
              </div>
              {currentUser.authenticated === true && (
                <div className="hidden sm:block sm:ml-6">
                  <div className="flex space-x-2">
                    <NavMenuItem to="/">Dashboard</NavMenuItem>
                    <NavMenuItem to="/projects">Projects</NavMenuItem>
                    {currentUser.permissions.includes('admin') && (
                      <Tooltip value="Admin Tools">
                        <NavMenuItem to="/admin">
                          <FontAwesomeIcon icon={faWrench} className="p-0 m-0"/>
                        </NavMenuItem>
                      </Tooltip>)}
                  </div>
                </div>
              )}
            </div>
            {currentUser.authenticated === true && (
              <div
                className="absolute inset-y-0 right-0 flex items-center pr-2 sm:static sm:inset-auto sm:ml-6 sm:pr-0">
                <Menu as="div" className="ml-3 relative">
                  <Menu.Button as={React.Fragment}>
                    <button className="bg-gray-800 flex text-sm rounded-full focus:outline-none">
                      <span className="sr-only">Open user menu</span>
                      <Gravatar className="h-8 w-8 rounded-full"
                                default="mp"
                                email={currentUser.email_address}
                                size={22}/>
                    </button>
                  </Menu.Button>
                  <Menu.Items aria-labelledby="user-menu"
                              aria-orientation="vertical"
                              className="origin-top-right absolute right-0 mt-2 w-48 rounded-md shadow-lg py-1 bg-white ring-1 ring-blue-900 ring-opacity-5">
                    <UserMenuItem to='/user/profile'>Your Profile</UserMenuItem>
                    <UserMenuItem to='/user/settings'>Settings</UserMenuItem>
                    <Menu.Item>
                      <a className="user-menu-item" href="/ui/logout">Sign Out</a>
                    </Menu.Item>
                  </Menu.Items>
                </Menu>
              </div>
            )}
          </div>
        </div>
        {currentUser.authenticated === true && (
          <div className="hidden sm:hidden">
            <div className="px-2 pt-2 pb-3 space-y-1">
              <a href="#"
                 className="bg-gray-900 text-white block px-3 py-2 rounded-md text-base font-medium">Dashboard</a>
              <a href="#"
                 className="text-gray-300 hover:bg-gray-700 hover:text-white block px-3 py-2 rounded-md text-base font-medium">Your
                Profile</a>
              <a href="#"
                 className="text-gray-300 hover:bg-gray-700 hover:text-white block px-3 py-2 rounded-md text-base font-medium">Settings</a>
              <a href="#"
                 className="text-gray-300 hover:bg-gray-700 hover:text-white block px-3 py-2 rounded-md text-base font-medium">Sign
                out</a>
            </div>
          </div>
        )}
      </nav>
    </header>
  )
}

Header.propTypes = {
  logo: PropTypes.string,
  service: PropTypes.string
}

export default Header
