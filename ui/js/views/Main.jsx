import React, { useContext } from 'react'

import { Router } from '@reach/router'

import Admin from './admin'
import Dashboard from './Dashboard'
import Project from './project'
import Projects from './project/Inventory'
import { NavBar, SideBar } from '../components/'
import User from './user/'
import { UserContext } from '../contexts'

export default function () {
    const currentUser = useContext(UserContext)
    if (currentUser.authenticated !== true) return null
    return (
        <>
            <NavBar />
            <div className="main">
                <SideBar />
                <div className="view-panel">
                    <Router>
                        <Dashboard path="/" default />
                        <Admin path="/admin/*" />
                        <Project path="/project/*" />
                        <Projects path="/projects/" />
                        <User path="/user/*" />
                    </Router>
                </div>
            </div>
        </>
    )
}
