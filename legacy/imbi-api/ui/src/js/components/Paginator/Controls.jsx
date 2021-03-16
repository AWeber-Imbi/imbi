import PropTypes from 'prop-types'
import React from 'react'

import { Buttons } from './Buttons'
import { PageSizeSelector } from './PageSizeSelector'
import { StateDisplay } from './StateDisplay'

function Controls({
  positionNounSingular,
  positionNounPlural,
  showPageSizeSelector,
  showStateDisplay
}) {
  return (
    <div className="align-middle items-center flex flex-column">
      <div className="align-middle flex-1 p-2 text-sm text-gray-700">
        {showStateDisplay && (
          <StateDisplay
            display={showStateDisplay}
            nounPlural={positionNounPlural}
            nounSingular={positionNounSingular}
          />
        )}
      </div>
      <PageSizeSelector display={showPageSizeSelector} />
      <Buttons />
    </div>
  )
}
Controls.defaultProps = {
  positionNounSingular: 'terms.record',
  positionNounPlural: 'terms.records',
  showPageSizeSelector: false,
  showStateDisplay: false
}
Controls.propTypes = {
  positionNounSingular: PropTypes.string,
  positionNounPlural: PropTypes.string,
  showPageSizeSelector: PropTypes.bool,
  showStateDisplay: PropTypes.bool
}
export { Controls }
