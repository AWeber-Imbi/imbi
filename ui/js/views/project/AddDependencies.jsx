import React, { useContext, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Jumbotron } from 'reactstrap'
import PropTypes from 'prop-types'

import {
    MultiSelectTable,
    Wizard,
    WizardContext,
    WizardPanel,
} from '../../components/'

export const propTypes = {
    setDataCallback: PropTypes.func,
    title: PropTypes.string,
}

export default function (props) {
    const wizard = useContext(WizardContext)
    const [data, setData] = useState([])
    const { t } = useTranslation()

    useEffect(() => {
        if (wizard.isActive(props.title) === true) props.setDataCallback(data)
    }, [data])

    useEffect(() => {
        if (wizard.isActive(props.title) && !wizard.isCompleted(props.title))
            wizard.setCompleted(props.title)
    }, [wizard.activePanel])

    const columns = [
        {
            name: 'team',
            sortable: true,
            title: `${t('addDependencies.team')}`,
        },
        {
            name: 'data_center',
            sortable: true,
            title: `${t('addDependencies.dataCenter')}`,
        },
        {
            name: 'project',
            sortable: true,
            title: `${t('addDependencies.project')}`,
        },
    ]

    const mockData = [
        {
            id: 'a93eeef4-b457-4700-b421-e575d1e4f6cd',
            team: `${t('addDependencies.controlPanel')}`,
            data_center: 'us-east-1',
            project: `${t('addDependencies.mapping')}`,
        }
    ]

    return (
        <WizardPanel title={props.title}>
            <p>{t('addDependencies.message')}</p>
            <MultiSelectTable
                columns={columns}
                data={[]}
                keyField="id"
                sortColumn="project"
                sortDirection="asc"
                updateCallback={setData}
            >
                <Jumbotron>
                    <h2>{t('addDependencies.noProject')}</h2>
                </Jumbotron>
            </MultiSelectTable>
        </WizardPanel>
    )
}
