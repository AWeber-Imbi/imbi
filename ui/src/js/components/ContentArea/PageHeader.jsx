import PropTypes from "prop-types"
import React from "react"

import {Icon} from "../";

function PageHeader({buttonClass, buttonIcon, buttonTitle, pageIcon, pageTitle}) {
  return(
    <div className="grid grid-cols-2 mb-1">
      <h1 className="inline-block text-xl pl-4 pt-2">
        <Icon icon={pageIcon} className="mr-2"/>
        {pageTitle}
      </h1>
      {buttonTitle && (
        <div className="text-right">
          <button className={buttonClass}>
            <Icon className="mr-3" icon={buttonIcon}/>
            {buttonTitle}
          </button>
        </div>
      )}
    </div>
  )
}

PageHeader.defaultProps = {
  buttonClass: "btn-green",
  buttonIcon: "fas plus-circle"
}

PageHeader.propTypes = {
  buttonClass: PropTypes.string,
  buttonIcon: PropTypes.string,
  buttonTitle: PropTypes.string,
  pageIcon: PropTypes.string.isRequired,
  pageTitle: PropTypes.string.isRequired
}

export {PageHeader}
