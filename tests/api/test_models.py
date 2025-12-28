from tornado import testing

from imbi import models
from tests import base


class NamespaceTestCase(base.TestCaseWithReset):

    TRUNCATE_TABLES = ['v1.namespaces']

    def setUp(self) -> None:
        super().setUp()
        self.namespace = self.create_namespace()

    @testing.gen_test
    async def test_namespace_model(self):
        namespace = await models.namespace(self.namespace['id'], self._app)
        self.assertEqual(namespace.name, self.namespace['name'])
        self.assertEqual(namespace.slug, self.namespace['slug'])
        self.assertEqual(namespace.icon_class, self.namespace['icon_class'])


class ProjectTypeTestCase(base.TestCaseWithReset):

    TRUNCATE_TABLES = ['v1.project_types']

    def setUp(self) -> None:
        super().setUp()
        self.project_type = self.create_project_type()

    @testing.gen_test
    async def test_namespace_model(self):
        value = await models.project_type(self.project_type['id'], self._app)
        self.assertEqual(value.name, self.project_type['name'])
        self.assertEqual(value.slug, self.project_type['slug'])
        self.assertEqual(value.icon_class, self.project_type['icon_class'])
