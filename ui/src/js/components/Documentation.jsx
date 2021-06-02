import PropTypes from 'prop-types'
import React, { useContext, useEffect } from 'react'

import { CodeBlock, Markdown } from '.'
import { Context } from '../state'

function Documentation({ code, preview, properties, title, urlPath }) {
  const [globalState, dispatch] = useContext(Context)

  useEffect(() => {
    dispatch({
      type: 'SET_CURRENT_PAGE',
      payload: {
        url: new URL(urlPath, globalState.baseURL.toString()),
        title: title
      }
    })
  }, [])
  return (
    <div className="space-y-5 p-4 w-full">
      <div className="ml-4 space-x-3">
        <h2 className="mb-3 text-gray-600 text-lg">Previews</h2>
        {preview}
      </div>
      <div className="ml-4 space-x-3">
        <h2 className="mb-3 text-gray-600 text-lg">Properties</h2>
        <Markdown>{properties.replace(/^\s+|\s+$/g, '').trimEnd()}</Markdown>
      </div>
      <div className="ml-4 space-x-3">
        <h2 className="mb-3 text-gray-600 text-lg">Code</h2>
        <div className="p-0 rounded shadow w-1/2">
          <CodeBlock language="jsx" value={code} />
        </div>
      </div>
    </div>
  )
}
Documentation.propTypes = {
  code: PropTypes.string.isRequired,
  preview: PropTypes.element.isRequired,
  properties: PropTypes.string.isRequired,
  title: PropTypes.string.isRequired,
  urlPath: PropTypes.string.isRequired
}
export { Documentation }
