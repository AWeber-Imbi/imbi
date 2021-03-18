import PropTypes from 'prop-types'
import React, { useContext, useEffect } from 'react'

import { Context } from '../../state'
import { WishedFutureState } from '../../components'

function Dependencies({ urlPath }) {
  const [state, dispatch] = useContext(Context)
  useEffect(() => {
    dispatch({
      type: 'SET_CURRENT_PAGE',
      payload: {
        title: 'project.dependencies',
        url: new URL(`${urlPath}/dependencies`, state.baseURL)
      }
    })
  }, [])
  return (
    <div className="pt-20 flex items-center justify-center">
      <WishedFutureState>
        This tab will provide a graph visualization of the projects that this
        project depends upon. In addition, there will be the option to edit the
        project&rsquo;s dependencies.
      </WishedFutureState>
    </div>
  )
}
Dependencies.propTypes = {
  urlPath: PropTypes.string.isRequired
}
export { Dependencies }
