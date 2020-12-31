import React, {useContext} from 'react'
import { Router } from '@reach/router'
import { UserContext } from '../../contexts'

function Admin() {
  const currentUser = useContext(UserContext)
  if (currentUser.authenticated !== true) return null
  return (
    <main className="content-between align-middle">




      <Router>
      </Router>
    </main>
  )
}

Admin.propTypes = {}

export default Admin
