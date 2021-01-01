import React, {useContext} from 'react'
import {Router} from '@reach/router'
import {UserContext} from '../../contexts'

import {default as Sidebar} from './Sidebar'


function Admin() {
  const currentUser = useContext(UserContext)
  if (currentUser.authenticated !== true) return null
  return (
    <div className="flex flex-row h-full">
      <Sidebar />
      <div className="flex flex-col w-auto p-4">
        Content
      </div>
    </div>
  )
}

Admin.propTypes = {}

export default Admin
