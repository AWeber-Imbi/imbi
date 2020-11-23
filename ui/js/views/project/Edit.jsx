import React, { useContext, useEffect, useReducer, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { compare } from 'fast-json-patch'
import { navigate } from '@reach/router'
import { useFetch, useMetadata, useHooks } from '../../hooks'
import { httpPatch } from '../../utils'
import { FetchContext } from '../../contexts'
import { Breadcrumb } from '../../components'

import {
    Col,
    Row,
    Button,
    Form,
    FormGroup,
    Label,
    Input,
    FormText,
} from 'reactstrap'
import { Select } from '../../components/'

export default (props) => {
    const { t } = useTranslation()
    const fetchMethod = useContext(FetchContext)
    const [projectData, dataErrorMessage] = useFetch('/projects/', undefined)
    const [metadata, metadataError] = useMetadata(false)
    const [dataToComapre, setDataToCompare] = useState([])
    const initialState = {
        id: '',
        name: '',
        slug: '',
        description: '',
        owned_by: '',
        project_type: '',
        data_center: '',
        configuration_system: '',
        deployment_type: '',
        orchestration_system: '',
    }
    const [data, setData] = useState(initialState)
    const [metaDataOption, setMetaDataOption] = useState({
        teams: [],
        project_types: [],
        data_centers: [],
        configuration_systems: [],
        deployment_types: [],
        orchestration_systems: [],
    })

    const { id } = props

    useEffect(() => {
        const filteredData =
            projectData && projectData.filter((item) => item.id === id)
        setData(filteredData && { ...filteredData[0] })
        setDataToCompare(filteredData && { ...filteredData[0] })
    }, [projectData])

    useEffect(() => {
        setMetaDataOption(metadata && metadata)
    }, [metadata])

    function onChangeCallback(e) {
        setData({ ...data, [e.target.name]: e.target.value })
    }

    function returnOption(row) {
        return { label: row.name, value: row.name }
    }

    async function createProjectRecord() {
        const message = 'Creating project record'
        const patchValue = compare(dataToComapre, data)
        const result = await httpPatch(
            fetchMethod,
            '/project' + '/' + data.id,
            patchValue
        )
        if (result.success === true) {
        } else {
            const err = result.data
        }
        return result.success
    }

    async function save() {
        const projectCreated = await createProjectRecord()
        if (!projectCreated) return
        navigate(`/projects/`)
    }

    function cancel() {
        navigate(`/projects/`)
    }

    return (
        <>
            <Breadcrumb
                items={[
                    { title: 'Project' },
                    {
                        title: 'Edit',
                        path: '/project/edit:id',
                    },
                ]}
            />
            <div className="wizard">
                <Form className="editpage">
                    <FormGroup row>
                        <Label for="projectName" sm={4}>
                            {t('common.name')}
                        </Label>
                        <Col sm={8}>
                            <Input
                                autoFocus
                                type="text"
                                name="name"
                                id="projectName"
                                onChange={onChangeCallback}
                                placeholder={t('addDetails.projectName')}
                                required
                                value={
                                    data && data.name !== null ? data.name : ''
                                }
                            />
                        </Col>
                    </FormGroup>
                    <FormGroup row>
                        <Label for="description" sm={4}>
                            {t('common.descriptionTitle')}
                        </Label>
                        <Col sm={8}>
                            <Input
                                type="text"
                                name="description"
                                id="description"
                                onChange={onChangeCallback}
                                placeholder={t('common.descriptionTitle')}
                                required
                                value={
                                    data && data.description !== null
                                        ? data.description
                                        : ''
                                }
                            />
                        </Col>
                    </FormGroup>
                    <FormGroup row>
                        <Label for="ownedBy" sm={4}>
                            {t('addDetails.ownedBy')}
                        </Label>
                        <Col sm={8}>
                            <Select
                                id="ownedBy"
                                options={
                                    metaDataOption &&
                                    metaDataOption.teams.map(returnOption)
                                }
                                name="owned_by"
                                onChangeCallback={onChangeCallback}
                                placeholder={t('addDetails.selectTeam')}
                                required
                                value={data && data.owned_by}
                            />
                        </Col>
                    </FormGroup>
                    <FormGroup row>
                        <Label for="projectType" sm={4}>
                            {t('addDetails.projectType')}
                        </Label>
                        <Col sm={8}>
                            <Select
                                id="projectType"
                                options={
                                    metaDataOption &&
                                    metaDataOption.project_types.map(
                                        returnOption
                                    )
                                }
                                name="project_type"
                                onChangeCallback={onChangeCallback}
                                placeholder={t('addDetails.selectProjectType')}
                                required
                                value={data && data.project_type}
                            />
                        </Col>
                    </FormGroup>
                    <FormGroup row>
                        <Label for="dataCenter" sm={4}>
                            {t('addDetails.dataCenter')}
                        </Label>
                        <Col sm={8}>
                            <Select
                                id="dataCenter"
                                options={
                                    metaDataOption &&
                                    metaDataOption.data_centers.map(
                                        returnOption
                                    )
                                }
                                name="data_center"
                                onChangeCallback={onChangeCallback}
                                placeholder={t('addDetails.selectDataCenter')}
                                required
                                value={data && data.data_center}
                            />
                        </Col>
                    </FormGroup>
                    <FormGroup row>
                        <Label for="configurationSystem" sm={4}>
                            {t('addDetails.configurationSystem')}
                        </Label>
                        <Col sm={8}>
                            <Select
                                id="configurationSystem"
                                options={
                                    metaDataOption &&
                                    metaDataOption.configuration_systems.map(
                                        returnOption
                                    )
                                }
                                name="configuration_system"
                                onChangeCallback={onChangeCallback}
                                placeholder={t(
                                    'addDetails.selectConfiguarationSystem'
                                )}
                                required
                                value={data && data.configuration_system}
                            />
                        </Col>
                    </FormGroup>
                    <FormGroup row>
                        <Label for="deploymentType" sm={4}>
                            {t('addDetails.deploymentType')}
                        </Label>
                        <Col sm={8}>
                            <Select
                                id="deploymentType"
                                options={
                                    metaDataOption &&
                                    metaDataOption.deployment_types.map(
                                        returnOption
                                    )
                                }
                                name="deployment_type"
                                onChangeCallback={onChangeCallback}
                                required
                                placeholder={t(
                                    'addDetails.selectDeploymentType'
                                )}
                                value={data && data.deployment_type}
                            />
                        </Col>
                    </FormGroup>
                    <FormGroup row>
                        <Label for="configurationSystem" sm={4}>
                            {t('addDetails.orchestrationSystem')}
                        </Label>
                        <Col sm={8}>
                            <Select
                                id="orchestrationSystem"
                                options={
                                    metaDataOption &&
                                    metaDataOption.orchestration_systems.map(
                                        returnOption
                                    )
                                }
                                name="orchestration_system"
                                onChangeCallback={onChangeCallback}
                                placeholder={t(
                                    'addDetails.selectOrchestrationSystem'
                                )}
                                required
                                value={data && data.orchestration_system}
                            />
                        </Col>
                    </FormGroup>
                    <Row>
                        <Col xs={12} className="text-right">
                            <Button
                                onClick={cancel}
                                color="secondary"
                                className="mr-2"
                            >
                                {t('common.cancel')}
                            </Button>
                            <Button onClick={save} color="primary">
                                {t('common.submit')}
                            </Button>
                        </Col>
                    </Row>
                </Form>
            </div>
        </>
    )
}
