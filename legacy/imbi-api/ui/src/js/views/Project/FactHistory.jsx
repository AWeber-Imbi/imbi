import PropTypes from 'prop-types'
import React, { useContext, useEffect } from 'react'

import { Context } from '../../state'
import { WishedFutureState } from '../../components'

function FactHistory({ urlPath }) {
  const [state, dispatch] = useContext(Context)
  useEffect(() => {
    dispatch({
      type: 'SET_CURRENT_PAGE',
      payload: {
        title: 'project.factHistory',
        url: new URL(`${urlPath}/fact-history`, state.baseURL)
      }
    })
  }, [])
  return (
    <div className="pt-20 flex items-center justify-center">
      <WishedFutureState>
        This tab will contain the history for fact changes in the project and
        include visualizations that shows health score changes over time.
      </WishedFutureState>
    </div>
  )
}
FactHistory.propTypes = {
  urlPath: PropTypes.string.isRequired
}
export { FactHistory }
