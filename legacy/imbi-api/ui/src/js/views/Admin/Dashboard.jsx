import React, { useContext, useEffect } from 'react'

import { Card } from '../../components'
import { Context } from '../../state'

function Dashboard() {
  const [state, dispatch] = useContext(Context)
  useEffect(() => {
    dispatch({
      type: 'SET_CURRENT_PAGE',
      payload: {
        title: 'admin.title',
        url: new URL('/ui/admin', state.baseURL)
      }
    })
  }, [])
  return (
    <Card>
      <div>
        Wished future state: Overview of things like user counts, projects, etc.
      </div>
    </Card>
  )
}
export { Dashboard }
