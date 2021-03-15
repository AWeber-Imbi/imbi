import PropTypes from 'prop-types'
import React, { Fragment, useState } from 'react'

import { Details } from './Details'
import { Facts } from './Facts'

function Overview({ project, factTypes, refresh }) {
  const [editing, setEditing] = useState({ details: false, facts: false })
  return (
    <Fragment>
      <div
        className={`flex flex-col lg:flex-row space-x-0 lg:space-x-3 space-y-3 lg:space-y-0 text-left text-gray-600 ${
          editing.details === false && editing.facts === false
            ? 'lg:items-stretch'
            : ''
        }`}>
        <div
          className={`flex-1 lg:w-6/12 w-full ${
            editing.details === false && editing.facts === false
              ? 'lg:flex-grow'
              : ''
          }`}>
          <Details
            project={project}
            editing={editing.details}
            refresh={refresh}
            onEditing={(isEditing) =>
              setEditing({ ...editing, details: isEditing })
            }
            shouldGrow={editing.details === false && editing.facts === false}
          />
        </div>
        <div
          className={`flex-1 lg:w-6/12 w-full ${
            editing.details === false && editing.facts === false
              ? 'lg:flex-grow'
              : ''
          }`}>
          <Facts
            project={project}
            factTypes={factTypes}
            editing={editing.facts}
            refresh={refresh}
            onEditing={(isEditing) =>
              setEditing({ ...editing, facts: isEditing })
            }
            shouldGrow={editing.details === false && editing.facts === false}
          />
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
