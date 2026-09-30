"""Freeze the AGE vertex labels and edge types.

The graph is being replaced by relational tables
(meta:docs/age-to-relational-implementation-plan.md, WP0.2). A new
label or edge type after the freeze has no table and no ETL mapping,
so its data would be lost at the cutover. The allowlists below are
Appendix A (labels) and Appendix B (edge types) of that plan. Change
them only together with the plan.

"""

import ast
import collections.abc
import pathlib
import re
import tomllib
import typing
import unittest

FREEZE_MESSAGE = (
    'New AGE labels are frozen; see '
    'meta:docs/age-to-relational-implementation-plan.md WP0.2.'
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SCAN_ROOTS = ('apps', 'libraries', 'plugins')
SCHEMATA = (
    REPO_ROOT
    / 'libraries'
    / 'common'
    / 'src'
    / 'imbi'
    / 'common'
    / 'graph'
    / 'schemata.toml'
)

# Appendix A: the 44 labels that graph/schemata.toml declares.
DECLARED_LABELS: typing.Final = frozenset(
    {
        'AIModel',
        'AIProvider',
        'APIKey',
        'Advisory',
        'AnalysisReport',
        'AnalysisResult',
        'Blocker',
        'Blueprint',
        'ClientCredential',
        'Comment',
        'CommentThread',
        'Component',
        'ComponentIdentifier',
        'ComponentNote',
        'ComponentRelease',
        'Conversation',
        'Deployment',
        'DocumentTemplate',
        'Environment',
        'IdentityConnection',
        'Integration',
        'LinkDefinition',
        'MCPServer',
        'Message',
        'OAuthClient',
        'OAuthIdentity',
        'Organization',
        'Permission',
        'PluginRegistration',
        'Project',
        'ProjectType',
        'Release',
        'Role',
        'ScoringPolicy',
        'ServiceAccount',
        'Session',
        'TOTPSecret',
        'Team',
        'TokenMetadata',
        'Upload',
        'User',
        'Webhook',
        'WebhookImplementation',
        'WebhookRule',
    }
)

# Appendix A: the 5 labels that code creates without a declaration.
UNDECLARED_LABELS: typing.Final = frozenset(
    {
        'AwsAccount',
        'Document',
        'LocalAuthConfig',
        'PasswordResetToken',
        'Tag',
    }
)

LABELS: typing.Final = DECLARED_LABELS | UNDECLARED_LABELS

# Appendix B: the 41 edge types.
EDGE_TYPES: typing.Final = frozenset(
    {
        'ACTIONS',
        'ALLOWED_FOR',
        'ATTACHED_TO',
        'BELONGS_TO',
        'BLOCKED_BY',
        'CAN_ACCESS',
        'CONTAINS',
        'DEPENDS_ON',
        'DEPLOYED_IN',
        'DEPLOYED_TO',
        'EXISTS_IN',
        'GRANTS',
        'HAS_ADVISORY',
        'HAS_ANALYSIS_REPORT',
        'HAS_CONVERSATION',
        'HAS_DEPLOYMENT',
        'HAS_IDENTITY',
        'HAS_NOTE',
        'HAS_RELEASE',
        'HAS_RESULT',
        'IDENTIFIED_BY',
        'IMPLEMENTED_BY',
        'INHERITS_FROM',
        'IN_THREAD',
        'ISSUED_TO',
        'LIKED',
        'MANAGED_BY',
        'MAPS_TO',
        'MEMBER_OF',
        'MFA_FOR',
        'OAUTH_IDENTITY',
        'ON_DOCUMENT',
        'OWNED_BY',
        'PERFORMED',
        'SERVED_BY',
        'SESSION_FOR',
        'TAGGED_WITH',
        'TARGETS',
        'TYPE',
        'USES',
        'USES_COMPONENT_RELEASE',
    }
)

# Graph model subclasses that are never written as a vertex, so their
# class name is not a label. ``Node`` is the shared base of the named
# models.
NEVER_WRITTEN_MODELS: typing.Final = frozenset(
    {
        'EnvironmentRef',
        'Node',
    }
)

EDGE_PATTERN = re.compile(r'\[[a-z_0-9]*:([A-Z_|]+)')
LABEL_PATTERN = re.compile(r'\([a-z_0-9]*:([A-Z][A-Za-z]+)')
GRAPH_MODEL_BASE = 'GraphModel'


def source_files() -> list[pathlib.Path]:
    """Return the non-test Python files under the scanned roots."""
    files: list[pathlib.Path] = []
    for root in SCAN_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob('*.py')):
            relative = path.relative_to(REPO_ROOT)
            if 'tests' in relative.parts:
                continue
            files.append(path)
    return files


def string_constants(tree: ast.AST) -> collections.abc.Iterator[str]:
    """Yield each string constant of a module.

    Docstrings are constants, and so are the literal parts of an
    f-string. Code outside strings is not scanned, so a slice such as
    ``rows[:LIMIT]`` does not match.

    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value


def base_name(node: ast.expr) -> str | None:
    """Return the last name of a class base (``models.Node`` → ``Node``)."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return base_name(node.value)
    return None


class Source(typing.NamedTuple):
    path: pathlib.Path
    tree: ast.Module


def parse_sources(
    files: collections.abc.Iterable[pathlib.Path],
) -> list[Source]:
    return [
        Source(path, ast.parse(path.read_text(), filename=str(path)))
        for path in files
    ]


def find_names(
    sources: collections.abc.Iterable[Source], pattern: re.Pattern[str]
) -> dict[str, set[str]]:
    """Map each name that ``pattern`` finds to the files that use it."""
    found: dict[str, set[str]] = {}
    for source in sources:
        relative = str(source.path.relative_to(REPO_ROOT))
        for value in string_constants(source.tree):
            for match in pattern.finditer(value):
                for name in match.group(1).split('|'):
                    if name:
                        found.setdefault(name, set()).add(relative)
    return found


def graph_model_classes(
    sources: collections.abc.Iterable[Source],
) -> dict[str, set[str]]:
    """Map each graph model subclass name to the files that define it.

    A class is a graph model when one of its bases, by its last name,
    is ``GraphModel`` or another graph model. The typed helpers use the
    class name as the label (``graph/cypher.py``).

    """
    classes: list[tuple[str, set[str], str]] = []
    for source in sources:
        relative = str(source.path.relative_to(REPO_ROOT))
        for node in ast.walk(source.tree):
            if isinstance(node, ast.ClassDef):
                bases = {
                    name
                    for name in map(base_name, node.bases)
                    if name is not None
                }
                classes.append((node.name, bases, relative))
    known = {GRAPH_MODEL_BASE}
    size = 0
    while size != len(known):
        size = len(known)
        known |= {name for name, bases, _path in classes if bases & known}
    found: dict[str, set[str]] = {}
    for name, bases, relative in classes:
        if bases & known:
            found.setdefault(name, set()).add(relative)
    return found


def unknown(
    found: dict[str, set[str]], allowed: frozenset[str]
) -> dict[str, list[str]]:
    return {
        name: sorted(paths)
        for name, paths in sorted(found.items())
        if name not in allowed
    }


class AgeLabelFreezeTestCase(unittest.TestCase):
    """The AGE label and edge type sets must not grow (WP0.2)."""

    sources: typing.ClassVar[list[Source]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.sources = parse_sources(source_files())

    def test_allowlist_sizes(self) -> None:
        self.assertEqual(len(DECLARED_LABELS), 44)
        self.assertEqual(len(LABELS), 49)
        self.assertEqual(len(EDGE_TYPES), 41)

    def test_declared_labels(self) -> None:
        with SCHEMATA.open('rb') as handle:
            declared = set(tomllib.load(handle)['vlabels']['name'])
        self.assertEqual(declared, DECLARED_LABELS, FREEZE_MESSAGE)

    def test_labels_in_strings(self) -> None:
        self.assertEqual(
            unknown(find_names(self.sources, LABEL_PATTERN), LABELS),
            {},
            FREEZE_MESSAGE,
        )

    def test_edge_types_in_strings(self) -> None:
        self.assertEqual(
            unknown(find_names(self.sources, EDGE_PATTERN), EDGE_TYPES),
            {},
            FREEZE_MESSAGE,
        )

    def test_graph_model_classes(self) -> None:
        self.assertEqual(
            unknown(
                graph_model_classes(self.sources),
                LABELS | NEVER_WRITTEN_MODELS,
            ),
            {},
            FREEZE_MESSAGE,
        )


class AgeLabelFreezeScannerTestCase(unittest.TestCase):
    """The scanner finds new names and ignores code outside strings."""

    @staticmethod
    def parse(code: str) -> list[Source]:
        path = REPO_ROOT / 'apps' / 'example.py'
        return [Source(path, ast.parse(code))]

    def test_new_label_in_string(self) -> None:
        found = find_names(
            self.parse("QUERY = 'MATCH (x:NewLabel) RETURN x'"),
            LABEL_PATTERN,
        )
        self.assertEqual(
            unknown(found, LABELS), {'NewLabel': ['apps/example.py']}
        )

    def test_new_label_in_fstring(self) -> None:
        found = find_names(
            self.parse("query = f'MATCH (x:NewLabel {{id: {x}}})'"),
            LABEL_PATTERN,
        )
        self.assertIn('NewLabel', unknown(found, LABELS))

    def test_new_edge_type_with_alternation(self) -> None:
        found = find_names(
            self.parse("Q = 'MATCH (a)-[:OWNED_BY|NEW_EDGE]->(b)'"),
            EDGE_PATTERN,
        )
        self.assertEqual(list(unknown(found, EDGE_TYPES)), ['NEW_EDGE'])

    def test_slice_outside_string(self) -> None:
        sources = self.parse('LIMIT = 5\nrows = []\nkept = rows[:LIMIT]\n')
        self.assertEqual(find_names(sources, EDGE_PATTERN), {})
        self.assertEqual(find_names(sources, LABEL_PATTERN), {})

    def test_new_graph_model_class(self) -> None:
        found = graph_model_classes(
            self.parse(
                'class Widget(models.GraphModel):\n'
                '    pass\n'
                'class Gadget(Widget):\n'
                '    pass\n'
                'class Other(pydantic.BaseModel):\n'
                '    pass\n'
            )
        )
        self.assertEqual(sorted(found), ['Gadget', 'Widget'])
