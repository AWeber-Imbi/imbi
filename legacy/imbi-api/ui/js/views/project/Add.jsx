import React, { useContext, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { navigate } from '@reach/router'
import uuidv4 from 'uuid/v4'

import { httpGet, httpPost } from '../../utils'
import { Loading, Panel, Wizard, WizardPanel } from '../../components'
import { FetchContext, UserContext } from '../../contexts'
import { useFetch } from '../../hooks'

import AddAutomations from './AddAutomations'
import AddDetails from './AddDetails'
import AddDependencies from './AddDependencies'
import AddFinish from './AddFinish'
import AddLinks from './AddLinks'
import { useMetadata, useHooks } from '../../hooks'

const breadcrumbs = [
    {
        title: 'Projects',
        path: '/projects/',
    },
    {
        title: 'Add Project',
        path: '/project/add',
    },
]

const completed = 'completed'
const completedIconClass = 'fas fa-check-circle text-success'
const erred = 'erred'
const erredIconClass = 'fas fa-exclamation-triangle text-danger'
const pending = 'pending'
const pendingIconClass = 'fa fa-hourglass-half text-secondary'

export default function () {
    const { t } = useTranslation()
    const fetchMethod = useContext(FetchContext)
    const [metadata, metadataError] = useMetadata(false)
    const [automations, setAutomations] = useState({
        gitlab_url: null,
        grafana_cookie_cutter: null,
        repository_cookie_cutter: null,
        setup_in_sentry: true,
    })
    const [dependencies, setDependencies] = useState([])
    const [links, setLinks] = useState([])
    const [project, setProject] = useState({
        id: uuidv4(),
        name: null,
        slug: null,
        description: null,
        owned_by: null,
        project_type: null,
        data_center: null,
        configuration_system: null,
        deployment_type: null,
        orchestration_system: null,
    })
    const [erred, setErred] = useState(false)
    const [finishProgress, setFinishProgress] = useState([])
    const [isDone, setIsDone] = useState(false)

    if (metadata === null) return <Loading />

    function setAutomationsCallback(values) {
        setAutomations(values)
    }

    function setDependenciesCallback(values) {
        setDependencies(values)
    }

    function setLinksCallback(values) {
        setLinks(values)
    }

    function setProjectCallback(values) {
        setProject(values)
    }

    function updateProgress(text, state, errorMessage = undefined) {
        let progress = [...finishProgress]
        if (state === completed || state === erred) {
            progress.pop()
        }
        let iconClass = null
        if (state === completed) iconClass = completedIconClass
        if (state === erred) iconClass = erredIconClass
        if (state === pending) iconClass = pendingIconClass
        progress.push({
            iconClass: iconClass,
            text: text,
            error: errorMessage,
        })
        setFinishProgress(progress)
    }

    async function createProjectRecord() {
        const message = 'Creating project record'
        updateProgress(message, pending)
        const result = await httpPost(fetchMethod, '/project/', project)
        if (result.success === true) {
            updateProgress(message, completed)
        } else {
            updateProgress(message, erred, result.data)
            setErred(true)
        }
        return result.success
    }

    async function createProjectLinks() {
        const message = 'Creating project links'
        updateProgress(message, pending)
        const result = await httpPost(fetchMethod, '/project/', project)
        if (result.success === true) {
            updateProgress(message, completed)
        } else {
            updateProgress(message, erred, result.data)
            setErred(true)
        }
        return result.success
    }

    async function onFinishClick() {
        const projectCreated = await createProjectRecord()
        if (!projectCreated) return
        setIsDone(true)
    }

    function onDoneClick() {
        navigate(`/projects/`)
    }

    return (
        <Panel breadcrumbs={breadcrumbs}>
            <Wizard
                isDone={isDone}
                erred={erred}
                onDoneClick={onDoneClick}
                onErredClick={onDoneClick}
                onFinishClick={onFinishClick}
            >
                <AddDetails
                    data={project}
                    metadata={metadata}
                    setDataCallback={setProjectCallback}
                    title={t('add.step1')}
                />
                <AddAutomations
                    data={automations}
                    metadata={metadata}
                    project={project}
                    setDataCallback={setAutomationsCallback}
                    title={t('add.step2')}
                />
                <AddDependencies
                    data={dependencies}
                    metadata={metadata}
                    setDataCallback={setDependenciesCallback}
                    title={t('add.step3')}
                />
                <AddLinks
                    automations={automations}
                    data={links}
                    metadata={metadata}
                    setDataCallback={setLinksCallback}
                    title={t('add.step4')}
                />
                <AddFinish
                    automations={automations}
                    dependencies={dependencies}
                    links={links}
                    metadata={metadata}
                    progress={finishProgress}
                    project={project}
                    title={t('add.step5')}
                />
            </Wizard>
        </Panel>
    )
}
