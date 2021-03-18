import PropTypes from 'prop-types'
import React from 'react'

import { Card, Icon } from '../'
import Logo from '../../../images/logo.svg'

function WishedFutureState({ children }) {
  return (
    <div style={{ width: '768px' }}>
      <Card>
        <div className="flex flex-row space-x-3">
          <img
            className="inline-block"
            style={{ height: '56px', width: '56px' }}
            src={Logo}
            alt=""
          />
          <div className="text-gray-700">
            <h1 className="text-lg font-medium mb-2">
              <Icon icon="fas info-circle" className="mr-2 text-blue-500" />
              Wished Future State
            </h1>
            <p>{children}</p>
          </div>
        </div>
      </Card>
    </div>
  )
}
WishedFutureState.propTypes = {
  children: PropTypes.string.isRequired
}
export { WishedFutureState }
