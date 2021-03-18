import PropTypes from 'prop-types'
import React, { useContext, useEffect } from 'react'

import { Context } from '../../state'
import { WishedFutureState } from '../../components'

function Notes({ urlPath }) {
  const [state, dispatch] = useContext(Context)
  useEffect(() => {
    dispatch({
      type: 'SET_CURRENT_PAGE',
      payload: {
        title: 'common.notes',
        url: new URL(`${urlPath}/notes`, state.baseURL)
      }
    })
  }, [])
  return (
    <div className="pt-20 flex items-center justify-center">
      <WishedFutureState>
        This tab will allow for the viewing and editing of project specific
        notes.
      </WishedFutureState>
    </div>
  )
}
Notes.propTypes = {
  urlPath: PropTypes.string.isRequired
}
export { Notes }
