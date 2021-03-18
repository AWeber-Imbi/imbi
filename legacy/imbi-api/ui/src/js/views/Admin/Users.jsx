import React, { useContext, useEffect } from 'react'

import { WishedFutureState } from '../../components'
import { Context } from '../../state'

function Users() {
  const [state, dispatch] = useContext(Context)
  useEffect(() => {
    dispatch({
      type: 'SET_CURRENT_PAGE',
      payload: {
        title: 'admin.manageUsers',
        url: new URL('/ui/admin/users', state.baseURL)
      }
    })
  }, [])
  return (
    <div className="flex-grow flex h-full items-center justify-center">
      <WishedFutureState>
        This page will allow you to edit local users and see attributes of LDAP
        users.
      </WishedFutureState>
    </div>
  )
}
export { Users }
