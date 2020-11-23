import React, { useContext, useState } from 'react'

import { Link } from '@reach/router'
import { Button, Dropdown, DropdownToggle, DropdownMenu, Nav } from 'reactstrap'

import { SettingsContext } from '../contexts'
import Tooltip from './Tooltip'

const savedState = localStorage.getItem('sidebar.iconsOnly') === 'true'

export default function (props) {
    const settings = useContext(SettingsContext)
    const [iconsOnly, setState] = useState(savedState)

    localStorage.setItem('sidebar.iconsOnly', iconsOnly.toString())

    function onClick(e) {
        e.preventDefault()
        setState(!iconsOnly)
    }

  return (
    <div id='sidebar' className={iconsOnly === true ? ' closed sidebar-wrapper' : 'sidebar-wrapper'}>
      <SideBarNav
        iconsOnly={iconsOnly}
        items={settings.sidebar || []} />
      <div className='toggle-sidebar'>
        <button className='btn btn-link' id='toggleSidebar' onClick={onClick}>
          <span className={'fas ' + (iconsOnly ? 'fa-angle-double-right' : 'fa-angle-double-left')}></span>
          {!iconsOnly ? ' Icons Only' : ''}
        </button>
        {iconsOnly &&
        <Tooltip placement='right' target='toggleSidebar' delay={100}>
          Expand Sidebar
        </Tooltip>}
      </div>
    </div>
  )
}

function SideBarNav(props) {
    const [opened, setOpened] = useState(undefined)

    function closeCallback() {
        setOpened(undefined)
    }

    function onToggle(e) {
        const title =
            e.target.children[0] === undefined
                ? e.target.title
                : e.target.children[0].title

        // Handle when the user clicks off the menu to another part of the page
        if (e.composed === true && title === '' && opened !== undefined) {
            setOpened(undefined)
            return
        }

        if (e.composed === true && title != opened) return
        setOpened(opened != title ? title : undefined)
    }

    return (
        <Nav vertical>
            {props.items.map((item) => {
                const key = 'nav-dropdown-' + item.title.replace(/ /gi, '_')
                return (
                    <Dropdown
                        nav
                        direction="right"
                        key={key}
                        isOpen={opened == item.title}
                        toggle={onToggle}
                    >
                        <DropdownToggle
                            id={key}
                            color={opened == item.title ? 'opened' : 'link'}
                        >
                            <span
                                className={item.icon}
                                title={item.title}
                            ></span>
                            {!props.iconsOnly ? item.title : ''}
                        </DropdownToggle>
                        {props.iconsOnly && (
                            <Tooltip placement="right" target={key}>
                                {item.title}
                            </Tooltip>
                        )}
                        <Menu items={item.items} onLinkClick={closeCallback} />
                    </Dropdown>
                )
            })}
        </Nav>
    )
}

function Menu(props) {
    return (
        <DropdownMenu>
            {props.items.map((item) => {
                return (
                    <Link
                        key={item.title.replace(/ /gi, '-') + '-nav-item'}
                        to={item.path}
                        className="dropdown-item"
                        onClick={props.onLinkClick}
                    >
                        {item.title}
                    </Link>
                )
            })}
        </DropdownMenu>
    )
}
