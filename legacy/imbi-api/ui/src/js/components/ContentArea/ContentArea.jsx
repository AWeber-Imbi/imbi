import PropTypes from "prop-types"
import React from "react"

import {PageHeader} from "./PageHeader"

function ContentArea({buttonClass, buttonIcon, buttonTitle, children, pageIcon, pageTitle}) {
  return(
    <div className="flex-auto p-4">
      <PageHeader buttonClass={buttonClass}
                  buttonIcon={buttonIcon}
                  buttonTitle={buttonTitle}
                  pageIcon={pageIcon}
                  pageTitle={pageTitle} />
      {children}
    </div>
  )
}

ContentArea.propTypes = {
  children: PropTypes.oneOfType([
    PropTypes.arrayOf(PropTypes.node),
    PropTypes.node,
    PropTypes.func
  ]),
  pageIcon: PropTypes.string.isRequired,
  pageTitle: PropTypes.string.isRequired,
  buttonClass: PropTypes.string,
  buttonIcon: PropTypes.string,
  buttonTitle: PropTypes.string
}

export {ContentArea}
