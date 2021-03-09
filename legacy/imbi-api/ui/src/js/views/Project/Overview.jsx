import PropTypes from 'prop-types'
import React, { Fragment } from 'react'

import { Details } from './Details'
import { Facts } from './Facts'

function Overview({ project }) {
  return (
    <Fragment>
      <div className="flex flex-row px-4 text-left text-gray-600">
        <div className="flex-1 w-6/12">
          <Details project={project} />
        </div>
        <div className="flex-1 w-6/12">
          <Facts project={project} />
        </div>
      </div>
    </Fragment>
  )
}
Overview.propTypes = {
  project: PropTypes.object.isRequired
}
export { Overview }
