import json
import uuid

import jsonpatch

from imbi.endpoints.project import link, project
from tests import base


class AsyncHTTPTestCase(base.TestCaseWithReset):

    ADMIN_ACCESS = True
    TRUNCATE_TABLES = [
        'v1.configuration_systems',
        'v1.data_centers',
        'v1.deployment_types',
        'v1.environments',
        'v1.orchestration_systems',
        'v1.project_link_types',
        'v1.project_types',
        'v1.namespaces'
    ]

    def setUp(self):
        super().setUp()
        self._configuration_system = self.create_configuration_system()
        self._data_center = self.create_data_center()
        self._deployment_type = self.create_deployment_type()
        self._environments = self.create_environments()
        self._namespace = self.create_namespace()
        self._orchestration_system = self.create_orchestration_system()
        self._project_link_type = self.create_project_link_type()
        self._project_type = self.create_project_type()

    def create_configuration_system(self):
        record = {
            'name': str(uuid.uuid4()),
            'description': str(uuid.uuid4()),
            'icon_class': 'fas fa-blind'
        }
        result = self.fetch('/admin/configuration_system', method='POST',
                            body=json.dumps(record).encode('utf-8'),
                            headers=self.headers)
        self.assertEqual(result.code, 200)
        return record['name']

    def create_data_center(self):
        record = {
            'name': str(uuid.uuid4()),
            'description': str(uuid.uuid4()),
            'icon_class': 'fas fa-blind'
        }
        result = self.fetch('/admin/data_center', method='POST',
                            body=json.dumps(record).encode('utf-8'),
                            headers=self.headers)
        self.assertEqual(result.code, 200)
        return record['name']

    def create_deployment_type(self):
        record = {
            'name': str(uuid.uuid4()),
            'description': str(uuid.uuid4()),
            'icon_class': 'fas fa-blind'
        }
        result = self.fetch('/admin/deployment_type', method='POST',
                            body=json.dumps(record).encode('utf-8'),
                            headers=self.headers)
        self.assertEqual(result.code, 200)
        return record['name']

    def create_environments(self):
        environments = []
        for iteration in range(0, 2):
            record = {
                'name': str(uuid.uuid4()),
                'description': str(uuid.uuid4()),
                'icon_class': 'fas fa-blind'
            }
            result = self.fetch('/admin/environment', method='POST',
                                body=json.dumps(record).encode('utf-8'),
                                headers=self.headers)
            self.assertEqual(result.code, 200)
            environments.append(record['name'])
        return environments

    def create_orchestration_system(self):
        record = {
            'name': str(uuid.uuid4()),
            'description': str(uuid.uuid4()),
            'icon_class': 'fas fa-blind'
        }
        result = self.fetch('/admin/orchestration_system', method='POST',
                            body=json.dumps(record).encode('utf-8'),
                            headers=self.headers)
        self.assertEqual(result.code, 200)
        return record['name']

    def create_project_link_type(self):
        record = {
            'link_type': str(uuid.uuid4()),
            'icon_class': 'fas fa-blind'
        }
        result = self.fetch('/admin/project_link_type', method='POST',
                            body=json.dumps(record).encode('utf-8'),
                            headers=self.headers)
        self.assertEqual(result.code, 200)
        return record['link_type']

    def create_project_type(self):
        record = {
            'name': str(uuid.uuid4()),
            'slug': str(uuid.uuid4()),
            'description': str(uuid.uuid4()),
            'icon_class': 'fas fa-blind'
        }
        result = self.fetch('/admin/project_type', method='POST',
                            body=json.dumps(record).encode('utf-8'),
                            headers=self.headers)
        self.assertEqual(result.code, 200)
        return record['name']

    def create_namespace(self):
        record = {
            'name': str(uuid.uuid4()),
            'slug': str(uuid.uuid4().hex),
            'icon_class': 'fas fa-blind',
            'maintained_by': []
        }
        result = self.fetch('/admin/namespace', method='POST',
                            body=json.dumps(record).encode('utf-8'),
                            headers=self.headers)
        self.assertEqual(result.code, 200)
        return record['name']

    def test_project_lifecycle(self):
        record = {
            'namespace': self._namespace,
            'name': str(uuid.uuid4()),
            'slug': str(uuid.uuid4().hex),
            'description': str(uuid.uuid4()),
            'data_center': self._data_center,
            'project_type': self._project_type,
            'configuration_system': self._configuration_system,
            'deployment_type': self._deployment_type,
            'orchestration_system': self._orchestration_system,
            'environments': self._environments
        }

        url = self.get_url('/projects/{}/{}'.format(
            self._namespace, record['name']))

        # Create
        result = self.fetch('/projects', method='POST',
                            body=json.dumps(record).encode('utf-8'),
                            headers=self.headers)
        self.assertEqual(result.code, 200)
        self.assertIsNotNone(result.headers['Date'])
        self.assertIsNone(result.headers.get('Last-Modified', None))
        self.assert_link_header_equals(result, url)
        self.assertEqual(
            result.headers['Cache-Control'], 'public, max-age={}'.format(
                project.RecordRequestHandler.TTL))
        new_value = json.loads(result.body.decode('utf-8'))
        self.assertEqual(
            new_value['created_by'], self.USERNAME[self.ADMIN_ACCESS])
        for field in ['created_by', 'last_modified_by']:
            del new_value[field]
        self.assertDictEqual(new_value, record)

        # PATCH
        updated = dict(record)
        updated['description'] = str(uuid.uuid4())
        patch = jsonpatch.make_patch(record, updated)
        patch_value = patch.to_string().encode('utf-8')

        result = self.fetch(
            url, method='PATCH', body=patch_value, headers=self.headers)
        self.assertEqual(result.code, 200)
        new_value = json.loads(result.body.decode('utf-8'))
        for field in ['created_by', 'last_modified_by']:
            self.assertEqual(
                new_value[field], self.USERNAME[self.ADMIN_ACCESS])
            del new_value[field]
        self.assertDictEqual(new_value, updated)

        # Patch no change
        result = self.fetch(
            url, method='PATCH', body=patch_value, headers=self.headers)
        self.assertEqual(result.code, 304)

        # GET
        result = self.fetch(url, headers=self.headers)
        self.assertEqual(result.code, 200)
        self.assertIsNotNone(result.headers['Date'])
        self.assertIsNotNone(result.headers['Last-Modified'])
        self.assert_link_header_equals(result, url)
        self.assertEqual(
            result.headers['Cache-Control'], 'public, max-age={}'.format(
                project.RecordRequestHandler.TTL))

        new_value = json.loads(result.body.decode('utf-8'))
        for field in ['created_by', 'last_modified_by']:
            self.assertEqual(
                new_value[field], self.USERNAME[self.ADMIN_ACCESS])
            del new_value[field]
        self.assertDictEqual(new_value, updated)

        # DELETE
        result = self.fetch(url, method='DELETE', headers=self.headers)
        self.assertEqual(result.code, 204)

        # GET record should not exist
        result = self.fetch(url, headers=self.headers)
        self.assertEqual(result.code, 404)

        # DELETE should fail as record should not exist
        result = self.fetch(url, method='DELETE', headers=self.headers)
        self.assertEqual(result.code, 404)

    def test_create_with_missing_fields(self):
        record = {
            'namespace': self._namespace,
            'name': str(uuid.uuid4()),
            'slug': str(uuid.uuid4().hex),
            'data_center': self._data_center,
            'project_type': self._project_type,
            'configuration_system': self._configuration_system,
            'deployment_type': self._deployment_type,
            'orchestration_system': self._orchestration_system,
            'environments': self._environments
        }

        url = self.get_url('/projects/{}/{}'.format(
            self._namespace, record['name']))

        # Create
        result = self.fetch('/projects', method='POST',
                            body=json.dumps(record).encode('utf-8'),
                            headers=self.headers)
        self.assertEqual(result.code, 200)
        self.assertIsNone(result.headers.get('Last-Modified', None))
        self.assert_link_header_equals(result, url)
        self.assertEqual(
            result.headers['Cache-Control'], 'public, max-age={}'.format(
                project.RecordRequestHandler.TTL))
        new_value = json.loads(result.body.decode('utf-8'))
        self.assertEqual(
            new_value['created_by'], self.USERNAME[self.ADMIN_ACCESS])
        for field in ['created_by', 'last_modified_by']:
            del new_value[field]
        record['description'] = None
        self.assertDictEqual(new_value, record)

    def test_dependencies(self):
        project_a = {
            'namespace': self._namespace,
            'name': str(uuid.uuid4()),
            'slug': str(uuid.uuid4().hex),
            'data_center': self._data_center,
            'project_type': self._project_type,
            'configuration_system': self._configuration_system,
            'deployment_type': self._deployment_type,
            'orchestration_system': self._orchestration_system,
            'environments': self._environments
        }

        result = self.fetch(
            '/projects', method='POST', headers=self.headers,
            body=json.dumps(project_a).encode('utf-8'))
        self.assertEqual(result.code, 200)

        project_b = {
            'namespace': self._namespace,
            'name': str(uuid.uuid4()),
            'slug': str(uuid.uuid4().hex),
            'data_center': self._data_center,
            'project_type': self._project_type,
            'configuration_system': self._configuration_system,
            'deployment_type': self._deployment_type,
            'orchestration_system': self._orchestration_system,
            'environments': self._environments
        }

        result = self.fetch(
            '/projects', method='POST', headers=self.headers,
            body=json.dumps(project_b).encode('utf-8'))
        self.assertEqual(result.code, 200)

        # Create the dependency
        result = self.fetch(
            '/projects/{}/{}/dependencies'.format(
                self._namespace, project_b['name']),
            method='POST', headers=self.headers,
            body=json.dumps({
                'dependency_namespace': self._namespace,
                'dependency_name': project_a['name']
            }).encode('utf-8'))
        self.assertEqual(result.code, 200)

        result = self.fetch(
            '/projects/{}/{}/dependencies'.format(
                self._namespace, project_b['name']),
            method='GET', headers=self.headers)
        self.assertEqual(result.code, 200)
        self.assertListEqual(
            json.loads(result.body.decode('utf-8')),
            [{
                'dependency_namespace': self._namespace,
                'dependency_name': project_a['name']
            }])

        result = self.fetch(
            '/projects/{}/{}/dependencies/{}/{}'.format(
                self._namespace, project_b['name'],
                self._namespace, project_a['name']),
            method='GET', headers=self.headers)
        self.assertEqual(result.code, 200)
        self.assertDictEqual(
            json.loads(result.body.decode('utf-8')),
            {
                'created_by': self.USERNAME[self.ADMIN_ACCESS],
                'namespace': self._namespace,
                'name': project_b['name'],
                'dependency_namespace': self._namespace,
                'dependency_name': project_a['name']
            })

        result = self.fetch(
            '/projects/{}/{}/dependencies/{}/{}'.format(
                self._namespace, project_b['name'],
                self._namespace, project_a['name']),
            method='DELETE', headers=self.headers)
        self.assertEqual(result.code, 204)

        result = self.fetch(
            '/projects/{}/{}/dependencies/{}/{}'.format(
                self._namespace, project_b['name'],
                self._namespace, project_a['name']),
            method='GET', headers=self.headers)
        self.assertEqual(result.code, 404)

    def test_links(self):
        project_record = {
            'namespace': self._namespace,
            'name': str(uuid.uuid4()),
            'slug': str(uuid.uuid4().hex),
            'data_center': self._data_center,
            'project_type': self._project_type,
            'configuration_system': self._configuration_system,
            'deployment_type': self._deployment_type,
            'orchestration_system': self._orchestration_system,
            'environments': self._environments
        }

        result = self.fetch('/projects', method='POST',
                            body=json.dumps(project_record).encode('utf-8'),
                            headers=self.headers)
        self.assertEqual(result.code, 200)

        record = {
            'namespace': self._namespace,
            'name': project_record['name'],
            'link_type': self._project_link_type,
            'url': 'https://github.com/AWeber/Imbi'
        }

        url = self.get_url('/projects/{}/{}/links/{}'.format(
            self._namespace, project_record['name'], self._project_link_type))

        # Create
        result = self.fetch(
            '/projects/{}/{}/links'.format(
                self._namespace, project_record['name']), headers=self.headers,
            method='POST', body=json.dumps(record).encode('utf-8'))
        self.assertEqual(result.code, 200)
        link_record = json.loads(result.body.decode('utf-8'))
        self.assert_link_header_equals(result, url)
        self.assertEqual(
            result.headers['Cache-Control'], 'public, max-age={}'.format(
                link.RecordRequestHandler.TTL))
        self.assertEqual(
            link_record['created_by'], self.USERNAME[self.ADMIN_ACCESS])
        self.assertEqual(link_record['url'], record['url'])

        # Get links
        result = self.fetch('/projects/{}/{}/links'.format(
            self._namespace, project_record['name']), headers=self.headers)
        self.assertEqual(result.code, 200)
        self.assert_link_header_equals(
            result, self.get_url('/projects/{}/{}/links'.format(
                self._namespace, project_record['name'])))
        records = []
        for row in json.loads(result.body.decode('utf-8')):
            for field in {'created_at', 'last_modified_at'}:
                del row[field]
            records.append(row)
        self.assertListEqual(records, [link_record])

        # PATCH
        updated = dict(record)
        updated['url'] = 'https://gitlab.com/AWeber/Imbi'
        patch = jsonpatch.make_patch(record, updated)
        patch_value = patch.to_string().encode('utf-8')

        result = self.fetch(
            url, method='PATCH', body=patch_value, headers=self.headers)
        self.assertEqual(result.code, 200)
        self.assert_link_header_equals(result, url)
        record = json.loads(result.body.decode('utf-8'))
        for field in {'created_by', 'last_modified_by'}:
            del record[field]
        self.assertDictEqual(record, updated)

        # Patch no change
        result = self.fetch(
            url, method='PATCH', body=patch_value, headers=self.headers)
        self.assertEqual(result.code, 304)
        self.assert_link_header_equals(result, url)

        # Get
        result = self.fetch(url, headers=self.headers)
        self.assertEqual(result.code, 200)
        record = json.loads(result.body.decode('utf-8'))
        for field in {'created_by', 'last_modified_by'}:
            del record[field]
        self.assertDictEqual(record, updated)

        # Delete
        result = self.fetch(url, method='DELETE', headers=self.headers)
        self.assertEqual(result.code, 204)

        # Get 404
        result = self.fetch(url, headers=self.headers)
        self.assertEqual(result.code, 404)
