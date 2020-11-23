import React, { useContext, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import PropTypes from 'prop-types'
import { Col, FormGroup, Input, Label } from 'reactstrap'

import { Select, Wizard, WizardContext, WizardPanel } from '../../components/'
import { SettingsContext } from '../../contexts'

export const propTypes = {
    data: PropTypes.object,
    setDataCallback: PropTypes.func,
    project: PropTypes.object,
    title: PropTypes.string,
}

export default function (props) {
    const [metadata, setMetadata] = useState(props.metadata)
    const settings = useContext(SettingsContext)

    const [data, setData] = useState(props.data)
    const [enabledOptions, setEnabledOptions] = useState({ gitlab_url: true })
    const [projectType, setProjectType] = useState(props.project.project_type)
    const [defaultGitlabURL, setDefaultGitlabURL] = useState('')
    const wizard = useContext(WizardContext)

    useEffect(() => {
        if (props.data != data) setData(props.data)
    }, [props.data])

    useEffect(() => {
        setProjectType(props.project.project_type)
    }, [props.project.project_type])

    useEffect(() => {
        if (wizard.isActive(props.title) === true) props.setDataCallback(data)
    }, [data])

    useEffect(() => {
        if (wizard.isActive(props.title) && !wizard.isCompleted(props.title))
            wizard.setCompleted(props.title)
    }, [wizard.activePanel])

    useEffect(() => {
        if (data.gitlab_url === null) {
            const index = metadata.teams.findIndex(
                (row) => row.name == props.project.owned_by
            )
            const teamSlug = index >= 0 ? metadata.teams[index].slug : undefined
            if (teamSlug !== undefined)
                setDefaultGitlabURL(
                    settings.gitlab_url +
                        '/' +
                        teamSlug +
                        '/' +
                        props.project.project_type +
                        '/' +
                        props.project.slug
                )
        }
    }, [metadata.teams, props.project, data.gitlab_url])

    function onChangeCallback(e) {
        setData({ ...data, [e.target.name]: e.target.value })
    }

    function toggleOption(e) {
        setEnabledOptions({
            ...enabledOptions,
            [e.target.dataset.target]: !enabledOptions[e.target.dataset.target],
        })
        if (e.target.dataset.target === 'gitlab_url') {
            if (!enabledOptions[e.target.dataset.target]) {
                if (data.gitlab_url === null) {
                    setData({ ...data, gitlab_url: defaultGitlabURL })
                }
            } else {
                setData({ ...data, gitlab_url: null })
            }
        }
    }

    function toggleSetupInSentry(e) {
        e.preventDefault()
        setData({ ...data, setup_in_sentry: !data.setup_in_sentry })
    }

    const { t } = useTranslation()

    return (
        <WizardPanel title={props.title}>
            <p>{t('addAutomation.message')}</p>
            <FormGroup>
                <Label onClick={toggleSetupInSentry}>
                    {t('addAutomation.createProject')}
                </Label>
                <div>
                    <button
                        className={
                            'btn btn-outline-secondary ' +
                            (data.setup_in_sentry === true
                                ? 'fas fa-toggle-on text-success'
                                : 'fas fa-toggle-off text-secondary')
                        }
                        id="setup-in-sentry"
                        onClick={toggleSetupInSentry}
                    />
                    <span
                        onClick={toggleSetupInSentry}
                        style={{ marginLeft: '1em' }}
                    >
                        {data.setup_in_sentry === true ? 'On' : 'Off'}
                    </span>
                </div>
            </FormGroup>
            <FormGroup>
                <Label onClick={toggleOption}>
                    {t('addAutomation.createGitlab')}
                </Label>
                <div className="input-group">
                    <div className="input-group-prepend">
                        <div
                            className="input-group-text"
                            data-target="gitlab_url"
                            onClick={toggleOption}
                        >
                            <span
                                className={
                                    enabledOptions.gitlab_url === true
                                        ? 'fas fa-toggle-on text-success'
                                        : 'fas fa-toggle-off text-secondary'
                                }
                                data-target="gitlab_url"
                                onClick={toggleOption}
                            />
                        </div>
                    </div>
                    <Input
                        disabled={!enabledOptions.gitlab_url}
                        name="gitlab_url"
                        id="gitlabURL"
                        onChange={onChangeCallback}
                        placeholder="Repository URL"
                        type="text"
                        value={
                            data.gitlab_url !== null
                                ? data.gitlab_url
                                : defaultGitlabURL
                        }
                    />
                </div>
            </FormGroup>
            <FormGroup>
                <Label for="repositoryCookieCutter" className="indent">
                    {t('addAutomation.repositoryCookie')}
                </Label>
                <Select
                    id="repositoryCookieCutter"
                    name="repository_cookie_cutter"
                    onChangeCallback={onChangeCallback}
                    options={metadata.cookie_cutters
                        .filter((row) => {
                            return (
                                row.type === 'project' &&
                                row.project_type == projectType
                            )
                        })
                        .map((row) => {
                            return { label: row.name, value: row.url }
                        })}
                    placeholder="Select Cookie Cutter"
                    style={{ marginLeft: '1em', marginTop: '.5em' }}
                    value={data.repository_cookie_cutter}
                />
            </FormGroup>
            <FormGroup>
                <Label for="grafanaCookieCutter" className="indent">
                    {t('addAutomation.grafanaCookie')}
                </Label>
                <Select
                    id="grafanaCookieCutter"
                    name="grafana_cookie_cutter"
                    options={metadata.cookie_cutters
                        .filter((row) => {
                            return (
                                row.type === 'dashboard' &&
                                row.project_type == projectType
                            )
                        })
                        .map((row) => {
                            return { label: row.name, value: row.url }
                        })}
                    onChangeCallback={onChangeCallback}
                    placeholder={t('addAutomation.placeholder')}
                    value={data.grafana_cookie_cutter}
                />
            </FormGroup>
        </WizardPanel>
    )
}
