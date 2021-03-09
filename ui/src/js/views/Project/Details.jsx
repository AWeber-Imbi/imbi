import PropTypes from 'prop-types'
import React from 'react'

function Details({ project }) {
  return (
    <div className="border-t border-b border-gray-200 ml-3">
      <dl>
        <div className="bg-gray px-4 py-2 sm:grid sm:grid-cols-2 sm:gap-4 sm:px-6">
          <dt className="text-sm font-medium text-gray-500">Namespace</dt>
          <dd className="mt-1 text-sm text-gray-900 sm:mt-0">
            {project.namespace}
          </dd>
          <dt className="text-sm font-medium text-gray-500">Project Type</dt>
          <dd className="mt-1 text-sm text-gray-900 sm:mt-0">
            {project.namespace}
          </dd>
        </div>
      </dl>
    </div>
  )
}
Details.propTypes = {
  project: PropTypes.object.isRequired
}
export { Details }
