"""
Tornado TemplateLoader that pulls data from a Python package installation

"""
import logging
import pkgutil
from os import path

from tornado import template

LOGGER = logging.getLogger(__name__)


class TemplateLoader(template.BaseLoader):
    """A template loader that loads from Python package data."""

    def __init__(self, debug=False, **kwargs):
        """Create a new instance of the loader, respecting the debug flag
        so that when set, templates are not cached, since changing templates
        does not trigger Tornado to restart.

        :param bool debug: Tornado's debug setting
        :param dict kwargs: Optional kwargs to pass through

        """
        super(TemplateLoader, self).__init__(**kwargs)
        self.debug = debug
        self.root = 'templates'

    def load(self, name, parent_path=None):
        """Loads a template, caching results in a local dict.

        :param str name: The name of the template
        :param str parent_path: The parent path for the template
        :rtype: str

        """
        name = self.resolve_path(name, parent_path=parent_path)
        with self.lock:
            if self.debug or name not in self.templates:
                self.templates[name] = self._create_template(name)
        return self.templates[name]

    def resolve_path(self, name, parent_path=None):
        """Resolve the Tornado template relative path.

        :param str name: The name of the template
        :param str parent_path: The parent path for the template
        :rtype: str

        """
        if parent_path and not parent_path.startswith('<') and \
            not parent_path.startswith('/') and \
                not name.startswith('/'):
            current_path = path.join(self.root, parent_path)
            file_dir = path.dirname(current_path)
            relative_path = path.join(file_dir, name)
            if relative_path.startswith(self.root):
                name = relative_path[len(self.root) + 1:]
        return path.normpath(name)

    def _create_template(self, name):
        """Loads the template from package data.

        :param str name: The relative path to the template file in the package
        :rtype: tornado.template.Template

        """
        LOGGER.debug('Loading %s', path.join(self.root, name))
        return template.Template(
            pkgutil.get_data(
                __name__.split('.')[0], path.join(self.root, name)),
            name=name, loader=self)
