import PropTypes from 'prop-types'
import React, { useContext, useEffect } from 'react'

import { WishedFutureState } from '../../components'
import { Context } from '../../state'

function Logs({ urlPath }) {
  const [state, dispatch] = useContext(Context)
  useEffect(() => {
    dispatch({
      type: 'SET_CURRENT_PAGE',
      payload: {
        title: 'common.logs',
        url: new URL(`${urlPath}/log`, state.baseURL)
      }
    })
  }, [])
  return (
    <div className="pt-20 flex items-center justify-center">
      <WishedFutureState>
        This tab will provide an interface for displaying project specific logs
        from the log aggregation service (ELK, Loggly, etc).
      </WishedFutureState>
    </div>
  )
}
Logs.propTypes = {
  urlPath: PropTypes.string.isRequired
}
export { Logs }
