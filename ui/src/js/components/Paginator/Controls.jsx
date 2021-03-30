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
    <div className="flex items-center text-sm text-gray-700">
      <div className="hidden md:inline-block p-2 whitespace-nowrap">
        {showStateDisplay && (
          <StateDisplay
            display={showStateDisplay}
            nounPlural={positionNounPlural}
            nounSingular={positionNounSingular}
          />
        )}
      </div>
      <div className="p-2 space-x-2 text-left md:text-right w-1/2 md:1-/3">
        <PageSizeSelector display={showPageSizeSelector} />
      </div>
      <div className="text-right w-1/2 md:1-/3">
        <Buttons />
      </div>
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
