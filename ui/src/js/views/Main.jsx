import PropTypes from "prop-types"
import React from "react"
import {Switch, Route} from "react-router-dom";

import {Admin, Dashboard, NotFound, OperationsLog, Projects, User} from "."
import {User as UserSchema} from "../schema"

function Main({user}) {
  return (
    <main className="flex flex-row flex-grow overflow-y-auto">
      <Switch>
        <Route path="/ui/admin">
          <Admin user={user}/>
        </Route>
        <Route path="/ui/operations-log">
          <OperationsLog user={user}/>
        </Route>
        <Route path="/ui/projects">
          <Projects user={user}/>
        </Route>
        <Route path="/ui/user">
          <User user={user}/>
        </Route>
        <Route path="/ui/">
          <Dashboard user={user}/>
        </Route>
        <Route path="*">
          <NotFound/>
        </Route>
      </Switch>
    </main>
  )
}

Main.propTypes = {
  user: PropTypes.exact(UserSchema)
}

export {Main}
