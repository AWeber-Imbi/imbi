import React, { useContext, useEffect } from 'react'

import { WishedFutureState } from '../components'
import { Context } from '../state'

function Reports() {
  const [state, dispatch] = useContext(Context)
  useEffect(() => {
    dispatch({
      type: 'SET_CURRENT_PAGE',
      payload: {
        title: 'terms.reports',
        url: new URL('/ui/reports', state.baseURL)
      }
    })
  }, [])
  return (
    <div className="flex-grow flex items-center justify-center">
      <WishedFutureState>
        This page will contain various reports for measuring compliance related
        KPIs.
      </WishedFutureState>
    </div>
  )
}
export { Reports }
