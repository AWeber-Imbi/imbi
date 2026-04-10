"""AGE operations for AI assistant conversations and messages."""

import datetime
import json
import logging
import typing
import uuid

from imbi_common import graph

from imbi_assistant import models

LOGGER = logging.getLogger(__name__)


async def create_conversation(
    db: graph.Graph,
    user_email: str,
    model: str,
) -> models.Conversation:
    """Create a new conversation."""
    now = datetime.datetime.now(datetime.UTC)
    conversation = models.Conversation(
        id=str(uuid.uuid4()),
        user_email=user_email,
        created_at=now,
        updated_at=now,
        model=model,
    )
    query = """
    CREATE (c:Conversation {{
        id: {id},
        user_email: {user_email},
        title: {title},
        created_at: {created_at},
        updated_at: {updated_at},
        model: {model},
        is_archived: {is_archived}
    }})
    WITH c
    OPTIONAL MATCH (u:User {{email: {user_email}}})
    FOREACH (_ IN CASE WHEN u IS NOT NULL THEN [1]
                       ELSE [] END |
        CREATE (u)-[:HAS_CONVERSATION]->(c)
    )
    RETURN c
    """
    await db.execute(
        query,
        {
            'id': conversation.id,
            'user_email': user_email,
            'title': conversation.title,
            'created_at': now.isoformat(),
            'updated_at': now.isoformat(),
            'model': model,
            'is_archived': False,
        },
        ['c'],
    )

    LOGGER.info(
        'Created conversation %s for user %s',
        conversation.id,
        user_email,
    )
    return conversation


async def get_conversation(
    db: graph.Graph,
    conversation_id: str,
    user_email: str,
) -> models.Conversation | None:
    """Get a conversation by ID, enforcing user ownership."""
    query = """
    MATCH (c:Conversation {{id: {id},
                            user_email: {user_email}}})
    RETURN c
    """
    records = await db.execute(
        query,
        {'id': conversation_id, 'user_email': user_email},
        ['c'],
    )
    if not records:
        return None

    data = graph.parse_agtype(records[0]['c'])
    return models.Conversation(**data)


async def list_conversations(
    db: graph.Graph,
    user_email: str,
    limit: int = 20,
    offset: int = 0,
    include_archived: bool = False,
) -> list[models.Conversation]:
    """List conversations for a user."""
    if include_archived:
        query = """
        MATCH (c:Conversation {{user_email: {user_email}}})
        RETURN c
        ORDER BY c.updated_at DESC
        """
    else:
        query = """
        MATCH (c:Conversation {{user_email: {user_email},
                                is_archived: false}})
        RETURN c
        ORDER BY c.updated_at DESC
        """
    # AGE does not support parameterized SKIP/LIMIT, so we
    # fetch all and slice in Python.
    records = await db.execute(
        query,
        {'user_email': user_email},
        ['c'],
    )
    conversations: list[models.Conversation] = []
    for record in records[offset : offset + limit]:
        data = graph.parse_agtype(record['c'])
        conversations.append(models.Conversation(**data))
    return conversations


async def add_message(
    db: graph.Graph,
    conversation_id: str,
    role: typing.Literal['user', 'assistant'],
    content: str,
    tool_use: list[dict[str, typing.Any]] | None = None,
    tool_results: (list[dict[str, typing.Any]] | None) = None,
    token_usage: dict[str, int] | None = None,
) -> models.Message:
    """Add a message to a conversation."""
    now = datetime.datetime.now(datetime.UTC)
    msg_id = str(uuid.uuid4())

    query = """
    MATCH (c:Conversation {{id: {conversation_id}}})
    SET c.updated_at = {created_at}
    WITH c
    OPTIONAL MATCH (c)-[:CONTAINS]->(existing:Message)
    WITH c, coalesce(max(existing.sequence), -1) + 1
         AS seq
    CREATE (m:Message {{
        id: {id},
        conversation_id: {conversation_id},
        role: {role},
        content: {content},
        tool_use: {tool_use},
        tool_results: {tool_results},
        created_at: {created_at},
        sequence: seq,
        token_usage: {token_usage}
    }})
    CREATE (c)-[:CONTAINS]->(m)
    RETURN m.sequence AS sequence
    """
    records = await db.execute(
        query,
        {
            'id': msg_id,
            'conversation_id': conversation_id,
            'role': role,
            'content': content,
            'tool_use': (json.dumps(tool_use) if tool_use else None),
            'tool_results': (
                json.dumps(tool_results) if tool_results else None
            ),
            'created_at': now.isoformat(),
            'token_usage': (json.dumps(token_usage) if token_usage else None),
        },
        ['sequence'],
    )

    if not records:
        raise ValueError(f'Conversation not found: {conversation_id}')
    sequence = graph.parse_agtype(records[0]['sequence'])

    return models.Message(
        id=msg_id,
        conversation_id=conversation_id,
        role=role,
        content=content,
        tool_use=tool_use,
        tool_results=tool_results,
        created_at=now,
        sequence=sequence,
        token_usage=token_usage,
    )


async def get_messages(
    db: graph.Graph,
    conversation_id: str,
    limit: int = 200,
) -> list[models.Message]:
    """Get messages for a conversation ordered by sequence."""
    query = """
    MATCH (m:Message {{conversation_id:
                       {conversation_id}}})
    RETURN m
    ORDER BY m.sequence ASC
    """
    records = await db.execute(
        query,
        {'conversation_id': conversation_id},
        ['m'],
    )

    messages: list[models.Message] = []
    for record in records[:limit]:
        data = graph.parse_agtype(record['m'])
        for field in (
            'tool_use',
            'tool_results',
            'token_usage',
        ):
            if isinstance(data.get(field), str):
                data[field] = json.loads(data[field])
        messages.append(models.Message(**data))
    return messages


async def count_messages(
    db: graph.Graph,
    conversation_id: str,
) -> int:
    """Count messages in a conversation."""
    query = """
    MATCH (m:Message {{conversation_id:
                       {conversation_id}}})
    RETURN count(m) AS count
    """
    records = await db.execute(
        query,
        {'conversation_id': conversation_id},
        ['count'],
    )
    if not records:
        return 0
    return graph.parse_agtype(records[0]['count']) or 0


async def update_conversation_title(
    db: graph.Graph,
    conversation_id: str,
    user_email: str,
    title: str,
) -> bool:
    """Update a conversation's title."""
    now = datetime.datetime.now(datetime.UTC)
    query = """
    MATCH (c:Conversation {{id: {id},
                            user_email: {user_email}}})
    SET c.title = {title},
        c.updated_at = {updated_at}
    RETURN c.id AS id
    """
    records = await db.execute(
        query,
        {
            'id': conversation_id,
            'user_email': user_email,
            'title': title,
            'updated_at': now.isoformat(),
        },
        ['id'],
    )
    return bool(records)


async def archive_conversation(
    db: graph.Graph,
    conversation_id: str,
    user_email: str,
) -> bool:
    """Archive a conversation."""
    now = datetime.datetime.now(datetime.UTC)
    query = """
    MATCH (c:Conversation {{id: {id},
                            user_email: {user_email}}})
    SET c.is_archived = true,
        c.updated_at = {updated_at}
    RETURN c.id AS id
    """
    records = await db.execute(
        query,
        {
            'id': conversation_id,
            'user_email': user_email,
            'updated_at': now.isoformat(),
        },
        ['id'],
    )
    return bool(records)


async def delete_conversation(
    db: graph.Graph,
    conversation_id: str,
    user_email: str,
) -> bool:
    """Delete a conversation and all its messages."""
    query = """
    MATCH (c:Conversation {{id: {id},
                            user_email: {user_email}}})
    OPTIONAL MATCH (c)-[:CONTAINS]->(m:Message)
    DETACH DELETE c, m
    RETURN count(c) AS deleted
    """
    records = await db.execute(
        query,
        {
            'id': conversation_id,
            'user_email': user_email,
        },
        ['deleted'],
    )
    deleted = graph.parse_agtype(records[0]['deleted']) if records else 0
    if deleted:
        LOGGER.info(
            'Deleted conversation %s for user %s',
            conversation_id,
            user_email,
        )
    return bool(deleted)
