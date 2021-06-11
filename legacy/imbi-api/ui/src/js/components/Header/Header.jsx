import { Link } from 'react-router-dom'
import PropTypes from 'prop-types'
import React, { Fragment } from 'react'

import { NavMenu } from './NavMenu'
import { NewMenu } from './NewMenu'
import { UserMenu } from './UserMenu'
import { User } from '../../schema'

function Header({ logo, service, authenticated, user }) {
  return (
    <header
      className={
        'flex-shrink bg-blue-700 h-13' + (authenticated !== true ? ' pb-1' : '')
      }>
      <nav className="p-2 flex flex-row">
        <Link to="/ui/" className="ml-2 h-8 w-8 flex-shrink">
          <img
            className={'h-8 w-8 mt-1' + (authenticated !== true ? ' mb-1' : '')}
            src={logo}
            alt={service}
          />
        </Link>
        {authenticated !== true && (
          <Link
            to="/ui/"
            className="ml-3 mt-2 flex-1 text-xl text-white hover:text-white">
            {service}
          </Link>
        )}
        {authenticated === true && (
          <Fragment>
            <NavMenu user={user} />
            <NewMenu user={user} />
            <UserMenu user={user} />
          </Fragment>
        )}
      </nav>
    </header>
  )
}

Header.propTypes = {
  logo: PropTypes.string.isRequired,
  service: PropTypes.string.isRequired,
  authenticated: PropTypes.bool.isRequired,
  user: PropTypes.exact(User).isRequired
}

export { Header }
