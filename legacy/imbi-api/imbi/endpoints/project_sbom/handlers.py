from __future__ import annotations

import collections
import http
import typing

import sprockets_postgres
from psycopg2 import sql

import imbi.models
import imbi.opensearch.project
from imbi import errors
from imbi.endpoints import base
from imbi.endpoints.project_sbom import graph, models
from imbi.endpoints.components import scoring


class SBOMInjectionHandler(base.PydanticHandlerMixin,
                           base.AuthenticatedRequestHandler):
    NAME = 'sbom-injection'

    async def put(self, project_id: str) -> None:
        try:
            project_id = int(project_id)
        except ValueError:  # pragma: no-cover -- URL pattern prevents this
            raise errors.ItemNotFound

        sbom: models.SBOM = self.parse_request_body_as(models.SBOM)
        target_ref = await self._find_project_ref(sbom)
        if target_ref not in {d.ref for d in sbom.dependencies}:
            raise errors.UnprocessableEntity(
                'target_ref %r is not in the SBoM dependency list', target_ref)

        components: dict[models.BOMRef, models.Component] = {}
        package_urls: set[models.PackageURL] = set()
        for component in sbom.components:
            components[component.bom_ref] = component
            if component.package_purl:
                package_urls.add(component.package_purl)

        project = await imbi.models.project(project_id, self.application)
        if not project:
            raise errors.ItemNotFound

        async with self.application.postgres_connector(
                on_error=self.on_postgres_error,
                on_duration=self.on_postgres_timing,
        ) as connector:
            connector: sprockets_postgres.PostgresConnector
            project_components: set[tuple[str, int]] = set()

            dependency_graph = graph.DependencyGraph(sbom.dependencies)
            version_map = ComponentVersionMap(connector, package_urls)
            for bom_ref in dependency_graph.all_dependencies(target_ref):
                try:
                    component = components[bom_ref]
                except KeyError:
                    raise errors.UnprocessableEntity(
                        'unknown component %r referenced as dependency of %r',
                        bom_ref, target_ref)
                if not component.purl:
                    self.logger.warning(
                        'skipping dependency %r, no package URL', bom_ref)
                elif not component.version:
                    self.logger.warning('skipping dependency %r, no version',
                                        bom_ref)
                else:
                    version_id = await version_map.get_version_id(component)
                    project_components.add(
                        (component.package_purl, version_id))
                    # update the project model instance for indexing purposes
                    # see _reindex_project() and imbi.models.project()
                    project.components.append({
                        'name': component.package_purl,
                        'version': component.version
                    })

            await self._insert_project_components(connector, project,
                                                  project_components)
            self.logger.debug('processed %s components for project %s(%s)',
                              len(project_components), project.slug,
                              project.id)

            await scoring.update_component_score_for_project(
                project.id, connector, self.application, index_project=False)

        await self._reindex_project(project)

        self.set_status(http.HTTPStatus.NO_CONTENT)

    async def _find_project_ref(self, sbom):
        target_ref: models.BOMRef | None = None
        if qargs := self.get_query_arguments('target_ref'):
            target_ref = qargs[0]
            self.logger.debug('using target_ref from query: %r', target_ref)
            if len(qargs) > 1:
                self.logger.warning(
                    'received %s target_ref query parameters, using %s',
                    len(qargs), target_ref)
        if target_ref is None and sbom.metadata.component:
            target_ref = sbom.metadata.component.bom_ref
        if target_ref is None:
            raise errors.BadRequest(
                'failed to find SBoM reference for project',
                detail=("Project's identifier cannot be determined from the "
                        'SBoM, you need to explicitly include it with the '
                        'target_ref query parameter'),
            )
        return target_ref

    async def _insert_project_components(
        self,
        connector: sprockets_postgres.PostgresConnector,
        project: imbi.models.Project,
        component_versions: typing.Iterable[tuple[str, int]],
        *,
        batch_size: int = 250,
    ) -> None:
        async with connector.transaction() as transaction:
            transaction: sprockets_postgres.PostgresConnector
            result = await transaction.execute(
                'DELETE FROM v1.project_components'
                ' WHERE project_id = %(project_id)s',
                {'project_id': project.id},
                metric_name='delete-project-components')
            self.logger.debug('removed %s components for project %s',
                              result.row_count, project.id)

            rows_to_add = [(project.id, package_url, version_id)
                           for package_url, version_id in component_versions]
            while rows_to_add:
                values = sql.SQL(',').join(
                    sql.Literal(r) for r in rows_to_add[:batch_size])
                query = sql.SQL(
                    'INSERT INTO v1.project_components ('
                    '            project_id, package_url, version_id)'
                    '     VALUES {}').format(values)
                await transaction.execute(
                    query.as_string(transaction.cursor.raw),
                    metric_name='insert-project-component-batch')
                del rows_to_add[:batch_size]

    async def _reindex_project(self, project: imbi.models.Project) -> None:
        index = imbi.opensearch.project.ProjectIndex(self.application)
        await index.index_document(project)


class ComponentVersionMap:
    def __init__(self, connector: sprockets_postgres.PostgresConnector,
                 package_urls: set[models.PackageURL]) -> None:
        self._purls_from_bom = package_urls.copy()
        self._cache: dict[models.PackageURL, models.VersionMap] = {}
        self._cache_primed = False
        self._connector = connector

    async def get_version_id(self, component: models.Component) -> int:
        if not self._cache_primed:
            await self._fetch_components()
        try:
            return self._cache[component.package_purl][component.version]
        except KeyError:
            return await self._insert_component_version(component)

    async def _fetch_components(self) -> None:
        """Fetch component versions from the database for PURLs in the BoM"""
        cache = collections.defaultdict(dict)
        result = await self._connector.execute(
            'SELECT id, package_url, version'
            '  FROM v1.component_versions'
            ' WHERE package_url = ANY(%s)', [list(self._purls_from_bom)],
            metric_name='get-component-versions')
        for row in result:
            cache[row['package_url']][row['version']] = row['id']
        self._cache.clear()
        self._cache.update(cache)
        self._cache_primed = True

    async def _insert_component_version(self,
                                        component: models.Component) -> int:
        try:
            component_versions = self._cache[component.package_purl]
        except KeyError:
            await self._connector.execute(
                'INSERT INTO v1.components(package_url, name, home_page,'
                '                          created_by)'
                '     VALUES (%(package_url)s, %(name)s, %(home_page)s,'
                '             %(created_by)s) '
                'ON CONFLICT (package_url) DO NOTHING', {
                    'package_url': component.package_purl,
                    'name': component.name,
                    'home_page': component.home_page,
                    'created_by': 'system',
                },
                metric_name='insert-component')
            component_versions = self._cache[component.package_purl] = {}

        try:
            return component_versions[component.version]
        except KeyError:
            result = await self._connector.execute(
                'INSERT INTO v1.component_versions(package_url, version)'
                '     VALUES (%(package_url)s, %(version)s) '
                'ON CONFLICT (package_url, version)'
                '  DO UPDATE SET version = %(version)s'
                '  RETURNING id', {
                    'package_url': component.package_purl,
                    'version': component.version,
                },
                metric_name='insert-component-version')
            component_versions[component.version] = result.row['id']
            return result.row['id']
