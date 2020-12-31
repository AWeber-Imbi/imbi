import React, {useContext} from 'react'
import {Router} from '@reach/router'
import {UserContext} from '../contexts'

import {Admin} from './admin/'

import User from './user'

function Main() {
  const currentUser = useContext(UserContext)
  if (currentUser.authenticated !== true) return null
  return (
    <main className="flex flex-row flex-grow overflow-y-auto">
      <Router primary={true} basepath="/ui">
        <Admin path="admin/*"/>
        <User path="user/*"/>
      </Router>
    </main>
  )
}

Main.propTypes = {}

export default Main
