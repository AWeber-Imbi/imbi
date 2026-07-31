"""The org-scoping join shared by every document query.

A document hangs off exactly one vertex -- a ``Project``, a
``ProjectType``, or a ``User`` -- and belongs to an organization only
through that vertex. Resolving it is therefore the authorization
boundary for documents: a query that scopes the join loosely returns
another organization's document.

That made it worth having in one place. Callers concatenate a fragment
with their own ``RETURN``/``WITH`` tail:

    query = _document_scope.BY_ID + 'RETURN d.created_by AS created_by'

Both fragments leave ``d`` (the document) and ``p``/``pt``/``u`` (the
attachment candidates, at most one non-null) in scope, and require an
``org_slug`` parameter -- plus ``document_id`` for :data:`BY_ID`.
"""

import typing

# The three attachment kinds and the guard that at least one resolved
# within the org. Everything above it differs only in how the document
# itself is matched.
_ATTACHMENT_TAIL: typing.LiteralString = """
    OPTIONAL MATCH (d)-[:ATTACHED_TO]->(p:Project)
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    OPTIONAL MATCH (d)-[:ATTACHED_TO]->(pt:ProjectType)
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    OPTIONAL MATCH (d)-[:ATTACHED_TO]->(u:User)
          -[:MEMBER_OF]->(:Organization {{slug: {org_slug}}})
    WITH d, p, pt, u
    WHERE (p IS NOT NULL OR pt IS NOT NULL OR u IS NOT NULL)
"""

#: One document by id, scoped to the org. Needs ``document_id``.
BY_ID: typing.LiteralString = (
    '\n    MATCH (d:Document {{id: {document_id}}})' + _ATTACHMENT_TAIL
)

#: Every document in the org.
ALL_IN_ORG: typing.LiteralString = (
    '\n    MATCH (d:Document)' + _ATTACHMENT_TAIL
)

#: Appended when only the document itself is needed downstream. The
#: attachment candidates have served their purpose as a guard, and
#: dropping them collapses the row-per-candidate fan-out.
DISTINCT_DOCUMENT: typing.LiteralString = '    WITH DISTINCT d\n'
