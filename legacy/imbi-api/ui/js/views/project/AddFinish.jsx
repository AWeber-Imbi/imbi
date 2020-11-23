import React, { useContext, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import hash from 'object-hash'
import { Button, Jumbotron } from 'reactstrap'
import PropTypes from 'prop-types'

import { Icon, Wizard, WizardContext, WizardPanel } from '../../components/'

export const propTypes = {
    automations: PropTypes.object,
    dependencies: PropTypes.array,
    links: PropTypes.array,
    options: PropTypes.object,
    progress: PropTypes.array,
    project: PropTypes.object,
    settings: PropTypes.object,
    title: PropTypes.string,
}

export default function (props) {
    const [links, setLinks] = useState(props.links)
    useEffect(() => {
        setLinks(props.links)
    }, [props.links])
    const { t } = useTranslation()
    const [progress, setProgress] = useState(props.progress)
    useEffect(() => setProgress(props.progress), [props.progress])

    return (
        <WizardPanel title={props.title}>
            {props.progress.length == 0 && (
                <Summary
                    automations={props.automations}
                    dependencies={props.dependencies}
                    links={links}
                    options={props.options}
                    settings={props.settings}
                    project={props.project}
                />
            )}
            {props.progress.length > 0 && <p>{t('addFinish.message')}</p>}
            <ul className="list-unstyled finish-progress">
                {progress.map((row) => {
                    return (
                        <li key={hash(row.text)}>
                            <Icon className={row.iconClass} /> {row.text}
                            {row.error && (
                                <>
                                    <br />
                                    <span
                                        style={{ marginLeft: '2.25em' }}
                                        className="text-danger"
                                    >
                                        {t('addFinish.error')}: {row.error}
                                    </span>
                                </>
                            )}
                        </li>
                    )
                })}
            </ul>
        </WizardPanel>
    )
}

function Summary(props) {
    const [links, setLinks] = useState(props.links)
    useEffect(() => {
        setLinks(props.links)
    }, [props.links])
    const { t } = useTranslation()
    const gccIndex =
        props.options === undefined
            ? -1
            : props.options.cookie_cutters.findIndex(
                  (row) => row.url == props.automations.grafana_cookie_cutter
              )
    const grafanaCookieCutter =
        gccIndex > 0 ? props.options.cookie_cutters[gccIndex].name : null
    const rccIndex =
        props.options === undefined
            ? -1
            : props.options.cookie_cutters.findIndex(
                  (row) => row.url == props.automations.repository_cookie_cutter
              )
    const repositoryCookieCutter =
        rccIndex > 0 ? props.options.cookie_cutters[rccIndex].name : null
    return (
        <>
            <p>
                Press &ldquo;Finish&rdquo; to add the project and perform any
                selected automation actions.
            </p>
            <h4 className="text-primary">{t('addFinish.projectOverview')}</h4>
            <dl className="summary row">
                <dt className="col-3">{t('addFinish.name')}</dt>
                <dd className="col-9">{props.project.name}</dd>
                <dt className="col-3">{t('addFinish.slug')}</dt>
                <dd className="col-9">{props.project.slug}</dd>
                <dt className="col-3">{t('addFinish.description')}</dt>
                <dd className="col-9">{props.project.description}</dd>
                <dt className="col-3">{t('addFinish.ownedBy')}</dt>
                <dd className="col-9">{props.project.owned_by}</dd>
                <dt className="col-3">{t('addFinish.projectType')}</dt>
                <dd className="col-9">{props.project.project_type}</dd>
                <dt className="col-3">{t('addFinish.dataCenter')}</dt>
                <dd className="col-9">{props.project.data_center}</dd>
                <dt className="col-3">{t('addFinish.configurationSystem')}</dt>
                <dd className="col-9">{props.project.configuration_system}</dd>
                <dt className="col-3">{t('addFinish.deploymentType')}</dt>
                <dd className="col-9">{props.project.deployment_type}</dd>
                <dt className="col-3">{t('addFinish.orchestrationSystem')}</dt>
                <dd className="col-9">{props.project.orchestration_system}</dd>
            </dl>
            <h4 className="text-primary">{t('addFinish.automations')}</h4>
            <ul className="summary">
                {props.automations.setup_in_sentry !== null && (
                    <li>{t('addFinish.setupSentry')}</li>
                )}
                {props.automations.gitlab_url !== null && (
                    <li>{t('addFinish.setupGitlab')}</li>
                )}
                {repositoryCookieCutter !== null && (
                    <li>
                        {t('addFinish.repoCookieCutter')}{' '}
                        <em>{repositoryCookieCutter}</em>
                    </li>
                )}
                {grafanaCookieCutter !== null && (
                    <li>
                        {t('addFinish.grafanaCookie')}{' '}
                        <em>{grafanaCookieCutter}</em>
                    </li>
                )}
            </ul>
            <h4 className="text-primary">{t('addFinish.dependencies')} </h4>
            {props.dependencies.length === 0 && (
                <small className="text-secondary">
                    {t('addFinish.noDependencies')}{' '}
                </small>
            )}
            <h4 className="text-primary">{t('addFinish.links')}</h4>
            {links.length === 0 && (
                <small className="text-secondary">
                    {t('addFinish.noLinks')}
                </small>
            )}
            <dl className="row summary">
                {links.map((row) => {
                    return (
                        <React.Fragment key={row.link_type}>
                            <dt className="col-2">{row.link_type}</dt>
                            <dd className="col-10">{row.url}</dd>
                        </React.Fragment>
                    )
                })}
            </dl>
        </>
    )
}
