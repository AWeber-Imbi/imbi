import PropTypes from "prop-types";
import React, {Component, Fragment} from "react"
import {Router as RRouter} from "@reach/router"

class LayoutComponent extends Component {
  static propTypes = {
    children: PropTypes.oneOfType([PropTypes.array, PropTypes.object, PropTypes.node])
  }

  render() {
    return (
      <Fragment>{this.props.children}</Fragment>
    )
  }
}

function Router({children, ...props}) {
  return (
    <RRouter component={LayoutComponent} {...props}>
      {children}
    </RRouter>
  )
}

Router.propTypes = {
  children: PropTypes.oneOfType([PropTypes.array, PropTypes.object, PropTypes.node])
}

export default Router

