import React, { useContext, useEffect } from 'react'

import { WishedFutureState } from '../../components'
import { Context } from '../../state'

function Groups() {
  const [state, dispatch] = useContext(Context)
  useEffect(() => {
    dispatch({
      type: 'SET_CURRENT_PAGE',
      payload: {
        title: 'admin.manageGroups',
        url: new URL('/ui/admin/groups', state.baseURL)
      }
    })
  }, [])
  return (
    <div className="flex-grow flex h-full items-center justify-center">
      <WishedFutureState>
        This page will allow you to edit local groups and see attributes of
        synced LDAP groups.
      </WishedFutureState>
    </div>
  )
}
export { Groups }
