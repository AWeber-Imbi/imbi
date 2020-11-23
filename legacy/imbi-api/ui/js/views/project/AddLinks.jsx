import React, { useContext, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import validate from 'validate.js'
import PropTypes from 'prop-types'
import { Button, Jumbotron } from 'reactstrap'

import {
    Select,
    Table,
    Wizard,
    WizardContext,
    WizardPanel,
} from '../../components/'

export const propTypes = {
    automations: PropTypes.object,
    data: PropTypes.array,
    options: PropTypes.array,
    setDataCallback: PropTypes.func,
    title: PropTypes.string,
}

export default function (props) {
    const [metadata, setMetadata] = useState(props.metadata)
    const [data, setData] = useState(props.data)
    const [error, setError] = useState(false)
    const wizard = useContext(WizardContext)
    const { t } = useTranslation()

    useEffect(() => {
        if (wizard.isActive(props.title) && !wizard.isCompleted(props.title))
            wizard.setCompleted(props.title)
    }, [wizard.activePanel])

    function createFilteredOptions() {
        const filtered = metadata.project_link_types
            .filter((link_type) => {
                return (
                    data.findIndex((row) => {
                        return row.link_type == link_type.link_type
                    }) < 0
                )
            })
            .map((row) => {
                return { label: row.link_type, value: row.link_type }
            })
        return filtered
    }

    const [options, setOptions] = useState(createFilteredOptions())

    useEffect(() => {
        setOptions(createFilteredOptions())
        if (props.data !== data) props.setDataCallback(data)
    }, [data])

    useEffect(() => {
        setOptions(createFilteredOptions())
    }, [metadata.project_link_types])

    useEffect(() => {
        if (props.automations.gitlab_url !== null) {
            const index = data.findIndex((row) => {
                return row.link_type == 'Repository'
            })
            if (index < 0) {
                setData([
                    ...data,
                    {
                        link_type: 'Repository',
                        url: props.automations.gitlab_url,
                    },
                ])
            }
        }
    }, [props.automations.gitlab_url])

    function addCallback(row) {
        setData([...data, row])
    }

    function deleteCallback(keyValue) {
        setData(data.filter((row) => row.link_type != keyValue))
    }

    function updateCallback(keyValue, updatedRow) {
        setData(
            data.map((row) => {
                if (row.link_type == keyValue) return updatedRow
                return row
            })
        )
    }

    function validationCallback(row) {
        let errors = []
        if (row.link_type === null) errors.push('link_type')
        const validURL = validate(
            { website: row.url },
            { website: { url: true } }
        )
        if (validURL !== undefined) errors.push('url')
        return errors
    }

    return (
        <WizardPanel title={props.title}>
            <p>{t('addLinks.message')}</p>
            <Table
                addCallback={addCallback}
                columns={[
                    {
                        headerStyle: { width: '30%' },
                        name: 'link_type',
                        options: options,
                        placeholder: `${t('addLinks.selectLinkType')}`,
                        editable: true,
                        required: true,
                        sortable: false,
                        style: { width: '30%' },
                        title: `${t('addLinks.linkType')}`,
                        type: 'select',
                    },
                    {
                        headerStyle: { width: 'auto' },
                        editable: true,
                        error: error,
                        name: 'url',
                        placeholder: `${t('addLinks.linkURL')}`,
                        required: true,
                        title: `${t('addLinks.url')}`,
                        type: 'string',
                    },
                ]}
                deleteCallback={deleteCallback}
                data={data}
                hideFilter={true}
                keyField="link_type"
                title="Project Link"
                updateCallback={updateCallback}
                validationCallback={validationCallback}
            >
                <Jumbotron>
                    <h2>{t('addLinks.noSerice')}</h2>
                    <hr className="my-2" />
                    <p>{t('addLinks.addFirstLink')}</p>
                </Jumbotron>
            </Table>
        </WizardPanel>
    )
}
