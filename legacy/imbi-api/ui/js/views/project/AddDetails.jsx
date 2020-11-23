import React, { useContext, useEffect, useReducer, useState } from 'react'
import { useTranslation } from 'react-i18next'
import PropTypes from 'prop-types'
import { Col, FormGroup, Input, Label } from 'reactstrap'

import { Select, Wizard, WizardContext, WizardPanel } from '../../components/'
import { SettingsContext } from '../../contexts'

export const propTypes = {
    setDataCallback: PropTypes.func,
    title: PropTypes.string,
}

export default function (props) {
    const { t } = useTranslation()
    const settings = useContext(SettingsContext)
    const [metadata, setMetadata] = useState(props.metadata)

    function dataReducer(state, action) {
        return { ...state, [action.field]: action.value }
    }

    const [data, setData] = useReducer(dataReducer, {
        id: props.data.id,
        name: props.data.name,
        slug: props.data.slug,
        description: props.data.description,
        owned_by: props.data.owned_by,
        project_type: props.data.project_type,
        data_center: props.data.data_center,
        configuration_system: props.data.configuration_system,
        deployment_type: props.data.deployment_type,
        orchestration_system: props.data.orchestration_system,
    })

    function onChangeCallback(e) {
        setData({ field: e.target.name, value: e.target.value })
        if (e.target.name == 'name') {
            setData({
                field: 'slug',
                value: e.target.value.toLowerCase().replace(/[_\s]/g, '-'),
            })
        }
    }

    const wizard = useContext(WizardContext)

    useEffect(() => {
        if (wizard.isActive(props.title) !== true) return
        wizard.setCompleted(
            props.title,
          data.name !== null &&
                data.name.length !== 0 &&
                data.slug !== null &&
                data.slug.length !== 0 &&
                data.owned_by !== null &&
                data.project_type !== null &&
                (metadata.data_centers.length === 0 ||
                    data.data_center !== null) &&
                (metadata.configuration_systems.length === 0 ||
                    data.configuration_system !== null) &&
                (metadata.deployment_types.length === 0 ||
                    data.deployment_type !== null) &&
                (metadata.orchestration_systems.length === 0 ||
                    data.orchestration_system !== null)
        )
        props.setDataCallback(data)
    }, [data])

    function returnOption(row) {
        return { label: row.name, value: row.name }
    }

    return (
        <WizardPanel placeholder={props.placeholder} title={props.title}>
            <p>{t('addDetails.message')}</p>
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
                        value={data.name !== null ? data.name : ''}
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
                            data.description !== null ? data.description : ''
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
                        options={metadata.teams.map(returnOption)}
                        name="owned_by"
                        onChangeCallback={onChangeCallback}
                        placeholder={t('addDetails.selectTeam')}
                        required
                        value={data.owned_by}
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
                        options={metadata.project_types.map(returnOption)}
                        name="project_type"
                        onChangeCallback={onChangeCallback}
                        placeholder={t('addDetails.selectProjectType')}
                        required
                        value={data.project_type}
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
                        options={metadata.data_centers.map(returnOption)}
                        name="data_center"
                        onChangeCallback={onChangeCallback}
                        placeholder={t('addDetails.selectDataCenter')}
                        required
                        value={data.data_center}
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
                        options={metadata.configuration_systems.map(
                            returnOption
                        )}
                        name="configuration_system"
                        onChangeCallback={onChangeCallback}
                        placeholder={t('addDetails.selectConfigurationSystem')}
                        required
                        value={data.configuration_system}
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
                        options={metadata.deployment_types.map(returnOption)}
                        name="deployment_type"
                        onChangeCallback={onChangeCallback}
                        required
                        placeholder={t('addDetails.selectDeploymentType')}
                        value={data.deployment_type}
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
                        options={metadata.orchestration_systems.map(
                            returnOption
                        )}
                        name="orchestration_system"
                        onChangeCallback={onChangeCallback}
                        placeholder={t('addDetails.selectOrchestrationSystem')}
                        required
                        value={data.orchestration_system}
                    />
                </Col>
            </FormGroup>
        </WizardPanel>
    )
}
