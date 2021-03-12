import PropTypes from 'prop-types'
import React, { Fragment } from 'react'

import { Details } from './Details'
import { Facts } from './Facts'

function Overview({ project, factTypes, refresh }) {
  return (
    <Fragment>
      <div className="flex flex-col lg:items-stretch lg:flex-row space-x-0 lg:space-x-3 space-y-3 lg:space-y-0 text-left text-gray-600">
        <div className="flex-1 lg:flex-grow lg:w-6/12 w-full">
          <Details project={project} refresh={refresh} />
        </div>
        <div className="flex-1 lg:flex-grow lg:w-6/12 w-full">
          <Facts factTypes={factTypes} project={project} refresh={refresh} />
        </div>
      </div>
    </Fragment>
  )
}
Overview.propTypes = {
  project: PropTypes.object.isRequired,
  factTypes: PropTypes.arrayOf(PropTypes.object).isRequired,
  refresh: PropTypes.func.isRequired
}
export { Overview }
