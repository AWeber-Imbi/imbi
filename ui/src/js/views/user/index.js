import React from "react"
import {Switch, Route} from "react-router-dom"

import {Profile} from "./Profile"

export default () => (
  <Switch>
    <Route path="/ui/user/profile" component={Profile}/>
  </Switch>
)
