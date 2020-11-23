import json
import uuid

import jsonpatch
from ietfparse import headers

from imbi.endpoints.project import link, project
from tests import common


class AsyncHTTPTestCase(common.AsyncHTTPTestCase):

    ADMIN = True

    def setUp(self):
        super().setUp()
        self._configuration_system = self.create_configuration_system()
        self._data_center = self.create_data_center()
        self._deployment_type = self.create_deployment_type()
        self._orchestration_system = self.create_orchestration_system()
        self._project_link_type = self.create_project_link_type()
        self._project_type = self.create_project_type()
        self._team = self.create_team()

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

    def create_team(self):
        record = {
            'name': str(uuid.uuid4()),
            'slug': str(uuid.uuid4().hex),
            'icon_class': 'fas fa-blind',
            'group': None
        }
        result = self.fetch('/admin/team', method='POST',
                            body=json.dumps(record).encode('utf-8'),
                            headers=self.headers)
        self.assertEqual(result.code, 200)
        return record['name']

    def test_project_lifecycle(self):
        record = {
            'id': str(uuid.uuid4()),
            'name': str(uuid.uuid4()),
            'slug': str(uuid.uuid4().hex),
            'description': str(uuid.uuid4()),
            'owned_by': self._team,
            'data_center': self._data_center,
            'project_type': self._project_type,
            'configuration_system': self._configuration_system,
            'deployment_type': self._deployment_type,
            'orchestration_system': self._orchestration_system
        }

        # Create
        result = self.fetch('/project/', method='POST',
                            body=json.dumps(record).encode('utf-8'),
                            headers=self.headers)
        self.assertEqual(result.code, 200)
        self.assertIsNotNone(result.headers['Date'])
        self.assertIsNone(result.headers.get('Last-Modified', None))
        self.assert_link_header_equals(
            result, self.get_url('/project/{}'.format(record['id'])))
        self.assertEqual(
            result.headers['Cache-Control'], 'public, max-age={}'.format(
                project.RequestHandler.TTL))
        new_value = json.loads(result.body.decode('utf-8'))
        self.assertDictEqual(new_value, record)

        # PATCH
        updated = dict(record)
        updated['description'] = str(uuid.uuid4())
        patch = jsonpatch.make_patch(record, updated)
        patch_value = patch.to_string().encode('utf-8')

        result = self.fetch(
            '/project/{}'.format(record['id']),
            method='PATCH', body=patch_value, headers=self.headers)
        self.assertEqual(result.code, 200)
        new_value = json.loads(result.body.decode('utf-8'))
        self.assertDictEqual(new_value, updated)

        # Patch no change
        result = self.fetch(
            '/project/{}'.format(record['id']),
            method='PATCH', body=patch_value, headers=self.headers)
        self.assertEqual(result.code, 304)

        # GET
        result = self.fetch(
            '/project/{}'.format(record['id']), headers=self.headers)

        self.assertEqual(result.code, 200)
        self.assertIsNotNone(result.headers['Date'])
        self.assertIsNotNone(result.headers['Last-Modified'])
        self.assertEqual(
            result.headers['Link'], '<{}>; rel="self"'.format(
                self.get_url('/project/{}'.format(record['id']))))
        self.assertEqual(
            result.headers['Cache-Control'], 'public, max-age={}'.format(
                project.RequestHandler.TTL))

        new_value = json.loads(result.body.decode('utf-8'))
        self.assertDictEqual(new_value, updated)

        # DELETE
        result = self.fetch(
            '/project/{}'.format(record['id']),
            method='DELETE', headers=self.headers)
        self.assertEqual(result.code, 204)

        # GET record should not exist
        result = self.fetch(
            '/project/{}'.format(record['id']), headers=self.headers)
        self.assertEqual(result.code, 404)

        # DELETE should fail as record should not exist
        result = self.fetch(
            '/project/{}'.format(record['id']),
            method='DELETE', headers=self.headers)
        self.assertEqual(result.code, 404)

    def test_create_with_missing_fields(self):
        record = {
            'id': str(uuid.uuid4()),
            'name': str(uuid.uuid4()),
            'slug': str(uuid.uuid4().hex),
            'owned_by': self._team,
            'data_center': self._data_center,
            'project_type': self._project_type,
            'configuration_system': self._configuration_system,
            'deployment_type': self._deployment_type,
            'orchestration_system': self._orchestration_system
        }

        # Create
        result = self.fetch('/project/', method='POST',
                            body=json.dumps(record).encode('utf-8'),
                            headers=self.headers)
        self.assertEqual(result.code, 200)
        self.assertIsNone(result.headers.get('Last-Modified', None))
        self.assertEqual(
            result.headers['Link'], '<{}>; rel="self"'.format(
                self.get_url('/project/{}'.format(record['id']))))
        self.assertEqual(
            result.headers['Cache-Control'], 'public, max-age={}'.format(
                project.RequestHandler.TTL))
        new_value = json.loads(result.body.decode('utf-8'))
        record['description'] = None
        self.assertDictEqual(new_value, record)

    def test_dependencies(self):
        svc1 = {
            'id': str(uuid.uuid4()),
            'name': str(uuid.uuid4()),
            'slug': str(uuid.uuid4().hex),
            'owned_by': self._team,
            'data_center': self._data_center,
            'project_type': self._project_type,
            'configuration_system': self._configuration_system,
            'deployment_type': self._deployment_type,
            'orchestration_system': self._orchestration_system
        }
        result = self.fetch('/project/', method='POST',
                            body=json.dumps(svc1).encode('utf-8'),
                            headers=self.headers)
        self.assertEqual(result.code, 200)
        self.assert_link_header_equals(
            result,
            self.get_url('/project/{}'.format(svc1['id'])))

        svc2 = {
            'id': str(uuid.uuid4()),
            'name': str(uuid.uuid4()),
            'slug': str(uuid.uuid4().hex),
            'owned_by': self._team,
            'data_center': self._data_center,
            'project_type': self._project_type,
            'configuration_system': self._configuration_system,
            'deployment_type': self._deployment_type,
            'orchestration_system': self._orchestration_system
        }
        result = self.fetch('/project/', method='POST',
                            body=json.dumps(svc2).encode('utf-8'),
                            headers=self.headers)
        self.assertEqual(result.code, 200)
        self.assert_link_header_equals(
            result,
            self.get_url('/project/{}'.format(svc2['id'])))

        data = {'dependency_id': svc1['id']}
        result = self.fetch('/project/{}/dependency'.format(svc2['id']),
                            method='POST',
                            body=json.dumps(data).encode('utf-8'),
                            headers=self.headers)
        link_url = self.get_url('/project/{}/dependency/{}'.format(
            svc2['id'], svc1['id']))
        self.assert_link_header_equals(result, link_url)

        # Get
        result = self.fetch(link_url, headers=self.headers)
        self.assertEqual(result.code, 200)
        self.assert_link_header_equals(result, link_url)

        # Test 405 on PATCH
        result = self.fetch(
            link_url, method='PATCH', body=b'{}', headers=self.headers)
        self.assertEqual(result.code, 405)

        # Get Collection
        result = self.fetch('/project/{}/dependencies'.format(
            svc2['id']), headers=self.headers)
        self.assertEqual(result.code, 200)
        self.assert_link_header_equals(
            result,
            self.get_url('/project/{}/dependencies'.format(svc2['id'])))
        self.assertListEqual(
            json.loads(result.body.decode('utf-8')),
            [{'dependency_id': svc1['id']}])

        # Delete
        result = self.fetch(link_url, method='DELETE', headers=self.headers)
        self.assertEqual(result.code, 204)

        # Get 404
        result = self.fetch(link_url, headers=self.headers)
        self.assertEqual(result.code, 404)

    def test_links(self):
        svc = {
            'id': str(uuid.uuid4()),
            'name': str(uuid.uuid4()),
            'slug': str(uuid.uuid4().hex),
            'owned_by': self._team,
            'data_center': self._data_center,
            'project_type': self._project_type,
            'configuration_system': self._configuration_system,
            'deployment_type': self._deployment_type,
            'orchestration_system': self._orchestration_system
        }
        result = self.fetch('/project/', method='POST',
                            body=json.dumps(svc).encode('utf-8'),
                            headers=self.headers)
        self.assertEqual(result.code, 200)
        self.assert_link_header_equals(
            result,
            self.get_url('/project/{}'.format(svc['id'])))

        record = {
            'project_id': svc['id'],
            'link_type': self._project_link_type,
            'url': 'https://github.com/AWeber/Imbi'
        }

        # Create
        result = self.fetch('/project/{}/link'.format(svc['id']),
                            method='POST',
                            body=json.dumps(record).encode('utf-8'),
                            headers=self.headers)
        link_record = json.loads(result.body.decode('utf-8'))
        self.assertEqual(result.code, 200)

        parsed = headers.parse_link(result.headers['Link'])
        link_url = parsed[0].target
        self.assertEqual(
            link_url, self.get_url('/project/{}/link/{}'.format(
                svc['id'], self._project_link_type)))
        self.assertEqual(
            result.headers['Cache-Control'], 'public, max-age={}'.format(
                link.RequestHandler.TTL))

        # Get links
        result = self.fetch('/project/{}/links'.format(svc['id']),
                            headers=self.headers)
        self.assertEqual(result.code, 200)
        self.assert_link_header_equals(
            result, self.get_url('/project/{}/links'.format(svc['id'])))
        self.assertListEqual(
            json.loads(result.body.decode('utf-8')), [link_record])

        # PATCH
        updated = dict(record)
        updated['url'] = 'https://gitlab.com/AWeber/Imbi'
        patch = jsonpatch.make_patch(record, updated)
        patch_value = patch.to_string().encode('utf-8')

        result = self.fetch(
            link_url, method='PATCH', body=patch_value, headers=self.headers)
        self.assertEqual(result.code, 200)
        self.assert_link_header_equals(result, link_url)
        self.assertDictEqual(json.loads(result.body.decode('utf-8')), updated)

        # Patch no change
        result = self.fetch(
            link_url, method='PATCH', body=patch_value, headers=self.headers)
        self.assertEqual(result.code, 304)
        self.assert_link_header_equals(result, link_url)

        # Get
        result = self.fetch(parsed[0].target, headers=self.headers)
        self.assertEqual(result.code, 200)
        self.assert_link_header_equals(result, link_url)
        record = json.loads(result.body.decode('utf-8'))
        self.assertDictEqual(record, updated)

        # Delete
        result = self.fetch(
            parsed[0].target, method='DELETE', headers=self.headers)
        self.assertEqual(result.code, 204)

        # Get 404
        result = self.fetch(parsed[0].target, headers=self.headers)
        self.assertEqual(result.code, 404)
