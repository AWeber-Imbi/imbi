import PropTypes from 'prop-types'
import React, { Fragment } from 'react'

import { Button, Icon } from '../'

function PageHeader({
  buttonClass,
  buttonIcon,
  buttonOnClick,
  buttonTitle,
  pageIcon,
  pageTitle
}) {
  return (
    <div className="grid grid-cols-2 mb-1">
      <h1 className="inline-block text-xl pl-4 pt-2">
        <Icon icon={pageIcon} className="mr-2" />
        {pageTitle}
      </h1>
      {buttonTitle && (
        <div className="text-right">
          <Button className={buttonClass} onClick={buttonOnClick}>
            <Fragment>
              <Icon className="mr-3" icon={buttonIcon} />
              {buttonTitle}
            </Fragment>
          </Button>
        </div>
      )}
    </div>
  )
}

PageHeader.defaultProps = {
  buttonClass: 'btn-green',
  buttonIcon: 'fas plus-circle'
}

PageHeader.propTypes = {
  buttonClass: PropTypes.string,
  buttonIcon: PropTypes.string,
  buttonOnClick: PropTypes.func,
  buttonTitle: PropTypes.string,
  pageIcon: PropTypes.string.isRequired,
  pageTitle: PropTypes.string.isRequired
}

export { PageHeader }
