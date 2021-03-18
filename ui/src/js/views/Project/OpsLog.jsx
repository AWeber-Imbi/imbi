import PropTypes from 'prop-types'
import React, { useContext, useEffect } from 'react'

import { WishedFutureState } from '../../components'
import { Context } from '../../state'

function OpsLog({ urlPath }) {
  const [state, dispatch] = useContext(Context)
  useEffect(() => {
    dispatch({
      type: 'SET_CURRENT_PAGE',
      payload: {
        title: 'operationsLog.title',
        url: new URL(`${urlPath}/operations-log`, state.baseURL)
      }
    })
  }, [])
  return (
    <div className="pt-20 flex items-center justify-center">
      <WishedFutureState>
        This tab will allow for a project specific view of the operations log
        entries.
      </WishedFutureState>
    </div>
  )
}
OpsLog.propTypes = {
  urlPath: PropTypes.string.isRequired
}
export { OpsLog }
