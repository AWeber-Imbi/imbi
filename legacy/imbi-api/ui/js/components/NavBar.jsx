import React, { useContext } from 'react'

import Gravatar from 'react-gravatar'
import { Link } from '@reach/router'
import {
    DropdownItem,
    DropdownMenu,
    DropdownToggle,
    Nav,
    UncontrolledDropdown,
} from 'reactstrap'

import { SettingsContext, UserContext } from '../contexts'

export default function (props) {
    const currentUser = useContext(UserContext)
    const settings = useContext(SettingsContext)

    return (
        <header>
            <nav className="navbar navbar-inverse navbar-expand-lg bg-primary fixed-top">
                <Link className="navbar-brand text-white h1 mb-0" to="/">
                    <span className="fab fa-earlybirds"></span>{' '}
                    {settings.service_name}
                </Link>
                {currentUser.username !== null && (
                    <Nav className="ml-auto" navbar>
                        <UncontrolledDropdown nav inNavbar>
                            <DropdownToggle nav caret>
                                <Gravatar
                                    email={currentUser.email_address}
                                    default="mp"
                                    size={22}
                                />{' '}
                                {currentUser.display_name}
                            </DropdownToggle>
                            <DropdownMenu right>
                                <DropdownItem>
                                    <Link to="/user/profile">
                                        <span className="far fa-id-card"></span>{' '}
                                        Profile
                                    </Link>
                                </DropdownItem>
                                <DropdownItem>
                                    <Link to="/user/settings">
                                        <span className="fas fa-wrench"></span>{' '}
                                        Settings
                                    </Link>
                                </DropdownItem>
                                <DropdownItem divider />
                                <DropdownItem>
                                    <a href="/ui/logout">
                                        <span className="fas fa-sign-out-alt"></span>{' '}
                                        Logout
                                    </a>
                                </DropdownItem>
                            </DropdownMenu>
                        </UncontrolledDropdown>
                    </Nav>
                )}
            </nav>
        </header>
    )
}
