import unittest

import tornado.httputil

from imbi import errors


class DefaultFunctionalityTests(unittest.TestCase):
    def test_that_error_url_can_be_configured(self):
        saved_error_url = errors.ERROR_URL
        try:
            errors.set_canonical_server('server.example.com')
            err = errors.ApplicationError(500, 'error-fragment', '')
            self.assertEqual('https://server.example.com/#error-fragment',
                             err.document['type'])
        finally:
            errors.ERROR_URL = saved_error_url

    def test_that_reason_is_set_from_status_code(self):
        err = errors.ApplicationError(500, 'fragment', '')
        self.assertEqual(tornado.httputil.responses[500], err.reason)

    def test_that_reason_is_title_if_set(self):
        err = errors.ApplicationError(500, 'fragment', '', title='title')
        self.assertEqual('title'.title(), err.reason)

    def test_that_unknown_status_codes_are_handled(self):
        err = errors.ApplicationError(1, 'fragment', '')
        self.assertEqual('Unknown Status Code', err.reason)

        err = errors.ApplicationError(600, 'fragment', '')
        self.assertEqual('Unknown Status Code', err.reason)

    def test_that_type_can_be_overridden(self):
        err = errors.ApplicationError(
            500,
            'error-fragment',
            '',
            type='https://example.com/troubleshooting')
        self.assertEqual('https://example.com/troubleshooting',
                         err.document['type'])

    def test_that_title_defaults_to_reason(self):
        err = errors.ApplicationError(500, 'fragment', '')
        self.assertEqual(tornado.httputil.responses[500],
                         err.document['title'])

    def test_that_detail_defaults_to_formatted_log_message(self):
        err = errors.ApplicationError(500, 'fragment', '1+1=%s', 1 + 1)
        self.assertEqual('1+1=2', err.document['detail'])

    def test_with_missing_log_args(self):
        err = errors.ApplicationError(500, 'fragment', '%s')
        self.assertEqual('%s', err.document['detail'])

    def test_with_unused_log_args(self):
        err = errors.ApplicationError(500, 'fragment', 'No args', 'arg')
        self.assertEqual('No args', err.document['detail'])


class SpecificErrorBehaviorTests(unittest.TestCase):
    def test_item_not_found_default_title(self):
        err = errors.ItemNotFound()
        self.assertEqual('Item not found', err.document['title'])

    def test_item_not_found_log_message(self):
        err = errors.ItemNotFound()
        self.assertEqual('Item not found', err.log_message)

    def test_method_not_allowed_log_message(self):
        err = errors.MethodNotAllowed('post')
        self.assertEqual('POST is not a supported HTTP method',
                         err.document['detail'])

    def test_unsupported_media_type_log_message(self):
        err = errors.UnsupportedMediaType('application/xml')
        self.assertEqual('application/xml is not a supported media type',
                         err.document['detail'])

    def test_database_error_defaults(self):
        err = errors.DatabaseError()
        self.assertEqual('Database Error', err.document['title'])
        self.assertEqual('Database Error', err.reason)
        self.assertEqual('Database failure', err.log_message)

    def test_database_error_with_exception(self):
        failure = RuntimeError('whatever')
        err = errors.DatabaseError(error=failure)
        self.assertEqual('Database Error', err.document['title'])
        self.assertEqual('Database Error', err.reason)
        self.assertEqual('Database failure: %s', err.log_message)
        self.assertEqual((failure, ), err.args)

    def test_database_error_with_explicit_title(self):
        err = errors.DatabaseError(title='No rows returned')
        self.assertEqual('No rows returned', err.document['title'])
        self.assertEqual('No rows returned'.title(), err.reason)
        self.assertEqual('Database failure', err.log_message)
