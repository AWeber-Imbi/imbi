import React, { useContext, useEffect, useState } from 'react'

import hash from 'object-hash'
import { Button, Nav, NavItem, NavLink, TabContent } from 'reactstrap'
import Icon from '../Icon'

import WizardContext from './WizardContext'

export default function (props) {
    const children = Array.isArray(props.children)
        ? props.children
        : [props.children]
    const [activePanel, setActivePanel] = useState(
        children.length > 0 ? hash(children[0].props.title) : null
    )
    const [erred, setErred] = useState(props.erred)
    useEffect(() => {
        setErred(props.erred)
    }, [props.erred])
    const [isDone, setIsDone] = useState(props.isDone)
    useEffect(() => {
        setIsDone(props.isDone)
    }, [props.isDone])
    const [finishClicked, setFinishClicked] = useState(false)
    const [nextDisabled, setNextDisabled] = useState(false)
    const [prevDisabled, setPrevDisabled] = useState(false)
    const [panels, setPanels] = useState(
        children.map((child) => {
            return hash(child.props.title)
        })
    )
    const [completedPanels, setCompletedPanels] = useState({})

    const lastPanel = hash(children[children.length - 1].props.title)

    function onClick(offset) {
        const index = panels.findIndex((p) => p == activePanel)
        setActivePanel(panels[index + offset])
    }

    function setCompleted(panel, completed = true) {
        if (panel === undefined) return
        setCompletedPanels({ ...completedPanels, [hash(panel)]: completed })
    }

    function onFinishClick(e) {
        e.preventDefault()
        setPrevDisabled(true)
        setFinishClicked(true)
        props.onFinishClick()
    }

    return (
        <WizardContext.Provider
            value={{
                activePanel: activePanel,
                isActive: (panel) => {
                    return hash(panel) == activePanel
                },
                isCompleted: (panel) => {
                    return completedPanels[hash(panel)] === true
                },
                completedPanels: completedPanels,
                setCompleted: setCompleted,
            }}
        >
            <div className="wizard">
                <Nav tabs>
                    <NavItems
                        clickCallback={setActivePanel}
                        prevDisabled={prevDisabled}
                    >
                        {children}
                    </NavItems>
                </Nav>
                <TabContent activeTab={activePanel}>{children}</TabContent>
                <div className="modal-footer tab-footer">
                    <Button
                        color="secondary"
                        data-direction="previous"
                        disabled={
                            prevDisabled ||
                            panels.findIndex((p) => p == activePanel) == 0
                        }
                        onClick={() => onClick(-1)}
                    >
                        <Icon className="fas fa-arrow-left"></Icon> Previous
                    </Button>
                    {!erred && !isDone && lastPanel != activePanel && (
                        <Button
                            color="primary"
                            data-direction="next"
                            disabled={completedPanels[activePanel] !== true}
                            onClick={() => onClick(1)}
                        >
                            Next{' '}
                            <Icon className="fas fa-arrow-right right"></Icon>
                        </Button>
                    )}
                    {!erred && !isDone && lastPanel == activePanel && (
                        <Button
                            color="success"
                            disabled={finishClicked}
                            onClick={onFinishClick}
                        >
                            Finish{' '}
                            <Icon className="fas fa-flag-checkered right"></Icon>
                        </Button>
                    )}
                    {!erred && isDone && lastPanel == activePanel && (
                        <Button color="primary" onClick={props.onDoneClick}>
                            <Icon className="fas fa-check-circle"></Icon> Done
                        </Button>
                    )}
                    {erred && (
                        <Button color="secondary" onClick={props.onErredClick}>
                            <Icon className="fas fa-exclamation-circle"></Icon>{' '}
                            Close
                        </Button>
                    )}
                </div>
            </div>
        </WizardContext.Provider>
    )
}

function NavItems(props) {
    const wizard = useContext(WizardContext)
    let completedPrevious = false
    return props.children.map((panel) => {
        const panelHash = hash(panel.props.title)
        let disabled = true
        if (completedPrevious === true || wizard.activePanel == panelHash)
            disabled = false
        else disabled = wizard.completedPanels[panelHash] !== true
        completedPrevious = wizard.completedPanels[panelHash]
        return (
            <NavItem key={panelHash}>
                <NavLink
                    active={wizard.activePanel == panelHash}
                    disabled={props.prevDisabled || disabled}
                    onClick={() => props.clickCallback(panelHash)}
                >
                    {panel.props.title}
                </NavLink>
            </NavItem>
        )
    })
}
