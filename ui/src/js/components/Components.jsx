import React, { useContext, useEffect } from 'react'
import { Link, Route } from 'react-router-dom'

import { Context } from '../state'

import { AlertPreview } from './Alert/AlertPreview'
import { BadgePreview } from './Badge/BadgePreview'

function ComponentList() {
  const [globalState, dispatch] = useContext(Context)
  useEffect(() => {
    dispatch({
      type: 'SET_CURRENT_PAGE',
      payload: {
        url: new URL('/ui/components', globalState.baseURL.toString()),
        title: 'Component Previews'
      }
    })
  }, [])
  return (
    <ul className="list-disc list-inside ml-5 space-y-3 text-gray-600">
      <li>
        <Link to="/ui/components/alert">Alert</Link>
      </li>
      <li>
        <Link to="/ui/components/badge">Badge</Link>
      </li>
    </ul>
  )
}

class ComponentPreviews extends React.PureComponent {
  render() {
    return (
      <div className="flex-grow flex flex-row p-4 z-10">
        <Route path="/ui/components" exact={true} component={ComponentList} />
        <Route path="/ui/components/alert" component={AlertPreview} />
        <Route path="/ui/components/badge" component={BadgePreview} />
      </div>
    )
  }
}
export { ComponentPreviews }
