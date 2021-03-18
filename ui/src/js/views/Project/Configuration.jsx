import PropTypes from 'prop-types'
import React, { useContext, useEffect } from 'react'

import { Context } from '../../state'
import { WishedFutureState } from '../../components'

function Configuration({ urlPath }) {
  const [state, dispatch] = useContext(Context)
  useEffect(() => {
    dispatch({
      type: 'SET_CURRENT_PAGE',
      payload: {
        title: 'common.configuration',
        url: new URL(`${urlPath}/configuration`, state.baseURL)
      }
    })
  }, [])
  return (
    <div className="pt-20 flex items-center justify-center">
      <WishedFutureState>
        This tab will provide an abstracted interface for editing the
        configuration in Consul, Vault, AWS SSM Parameter Store, and K8s
        Configuration Maps.
      </WishedFutureState>
    </div>
  )
}
Configuration.propTypes = {
  urlPath: PropTypes.string.isRequired
}
export { Configuration }
