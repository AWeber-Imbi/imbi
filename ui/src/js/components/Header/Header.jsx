import {Link} from '@reach/router'
import React, {useContext} from 'react'
import PropTypes from "prop-types"

import {default as NavMenu} from './NavMenu'
import {default as NewMenu} from './NewMenu'
import {default as UserMenu} from './UserMenu'

import {UserContext} from '../../contexts'

function Header({logo, service}) {
  const currentUser = useContext(UserContext)
  return (
    <header className={"flex-shrink bg-blue-700 h-13 border-b-2 border-blue-700" + (currentUser.authenticated !== true ? ' pb-1' : '')}>
      <nav className="p-2 flex flex-row">
        <Link to="/ui/" className="h-8 w-8 flex-shrink">
          <img className={"h-8 w-8 mt-1" + (currentUser.authenticated !== true ? ' mb-1' : '')}
               src={logo} alt={service} />
        </Link>
        {currentUser.authenticated !== true && (
          <Link to="/ui/" className="ml-3 mt-2 flex-1 text-xl text-white hover:text-white">
            {service}
          </Link>
        )}
        <NavMenu currentUser={currentUser} />
        <NewMenu currentUser={currentUser} />
        <UserMenu currentUser={currentUser} />
      </nav>
    </header>
  )
}

Header.propTypes = {
  logo: PropTypes.string,
  service: PropTypes.string
}

export default Header
