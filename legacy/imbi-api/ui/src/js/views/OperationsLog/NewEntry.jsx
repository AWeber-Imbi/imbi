import PropTypes from 'prop-types'
import React, { useContext, useEffect } from 'react'

import { Context } from '../../state'
import { User } from '../../schema'
import { WishedFutureState } from '../../components'

function NewEntry() {
  const [state, dispatch] = useContext(Context)
  useEffect(() => {
    dispatch({
      type: 'SET_CURRENT_PAGE',
      payload: {
        title: 'operationsLogNewEntry.title',
        url: new URL('/ui/operations-log/create', state.baseURL)
      }
    })
  }, [])
  return (
    <div className="flex-grow flex items-center justify-center">
      <WishedFutureState>
        This page will let you manually add an operations log entry. Ideally
        these entries would be made as part of a CI pipeline process. In
        addition, we&rsquo;d like to update the slackbot to allow for entries by
        way of slack.
      </WishedFutureState>
    </div>
  )
}
NewEntry.propTypes = {
  user: PropTypes.exact(User)
}
export { NewEntry }
