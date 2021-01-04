import React, {useContext} from "react"
import {Switch, Route} from "react-router-dom";

import {Admin, Dashboard, NotFound, User} from "."
import {UserContext} from "../contexts"

function Main() {
  const currentUser = useContext(UserContext)
  if (currentUser.authenticated !== true) return null
  return (
    <main className="flex flex-row flex-grow overflow-y-auto">
      <Switch>
        <Route path="/ui/admin" component={Admin}/>
        <Route path="/ui/user" component={User}/>
        <Route path="/ui/" component={Dashboard}/>
        <Route path="*" component={NotFound}/>
      </Switch>
    </main>
  )
}

Main.propTypes = {}

export default Main
