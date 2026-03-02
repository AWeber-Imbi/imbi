"""Neo4j operations for AI assistant conversations and messages."""

import datetime
import json
import logging
import typing
import uuid

from imbi_common import neo4j

from imbi_api.assistant import models

LOGGER = logging.getLogger(__name__)


async def create_conversation(
    user_email: str,
    model: str,
) -> models.Conversation:
    """Create a new conversation.

    Args:
        user_email: Email of the conversation owner.
        model: Claude model identifier to use.

    Returns:
        The created Conversation.

    """
    now = datetime.datetime.now(datetime.UTC)
    conversation = models.Conversation(
        id=str(uuid.uuid4()),
        user_email=user_email,
        created_at=now,
        updated_at=now,
        model=model,
    )
    query = """
    CREATE (c:Conversation {
        id: $id,
        user_email: $user_email,
        title: $title,
        created_at: datetime($created_at),
        updated_at: datetime($updated_at),
        model: $model,
        is_archived: $is_archived
    })
    WITH c
    OPTIONAL MATCH (u:User {email: $user_email})
    FOREACH (_ IN CASE WHEN u IS NOT NULL THEN [1]
                       ELSE [] END |
        CREATE (u)-[:HAS_CONVERSATION]->(c)
    )
    RETURN c
    """
    async with neo4j.run(
        query,
        id=conversation.id,
        user_email=user_email,
        title=conversation.title,
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
        model=model,
        is_archived=False,
    ) as result:
        await result.consume()

    LOGGER.info(
        'Created conversation %s for user %s',
        conversation.id,
        user_email,
    )
    return conversation


async def get_conversation(
    conversation_id: str,
    user_email: str,
) -> models.Conversation | None:
    """Get a conversation by ID, enforcing user ownership.

    Args:
        conversation_id: UUID of the conversation.
        user_email: Email of the requesting user.

    Returns:
        The Conversation if found and owned by user, else None.

    """
    query = """
    MATCH (c:Conversation {id: $id, user_email: $user_email})
    RETURN c
    """
    async with neo4j.run(
        query, id=conversation_id, user_email=user_email
    ) as result:
        records = await result.data()

    if not records:
        return None

    data = neo4j.convert_neo4j_types(records[0]['c'])
    return models.Conversation(**data)


async def list_conversations(
    user_email: str,
    limit: int = 20,
    offset: int = 0,
    include_archived: bool = False,
) -> list[models.Conversation]:
    """List conversations for a user.

    Args:
        user_email: Email of the requesting user.
        limit: Maximum number of results.
        offset: Number of results to skip.
        include_archived: Whether to include archived conversations.

    Returns:
        List of conversations ordered by most recently updated.

    """
    archive_filter = '' if include_archived else 'AND c.is_archived = false'
    query = f"""
    MATCH (c:Conversation {{user_email: $user_email}})
    WHERE true {archive_filter}
    RETURN c
    ORDER BY c.updated_at DESC
    SKIP $offset
    LIMIT $limit
    """
    conversations: list[models.Conversation] = []
    async with neo4j.run(
        query,
        user_email=user_email,
        limit=limit,
        offset=offset,
    ) as result:
        records = await result.data()

    for record in records:
        data = neo4j.convert_neo4j_types(record['c'])
        conversations.append(models.Conversation(**data))
    return conversations


async def add_message(
    conversation_id: str,
    role: typing.Literal['user', 'assistant'],
    content: str,
    tool_use: list[dict[str, typing.Any]] | None = None,
    tool_results: list[dict[str, typing.Any]] | None = None,
    token_usage: dict[str, int] | None = None,
) -> models.Message:
    """Add a message to a conversation.

    Args:
        conversation_id: UUID of the conversation.
        role: Message role (user or assistant).
        content: Message text content.
        tool_use: Tool use blocks from Claude response.
        tool_results: Tool execution results.
        token_usage: Token usage stats.

    Returns:
        The created Message.

    """
    now = datetime.datetime.now(datetime.UTC)
    msg_id = str(uuid.uuid4())

    # Atomic: find max sequence and create new message in a
    # single query to avoid sequence number race conditions
    query = """
    MATCH (c:Conversation {id: $conversation_id})
    SET c.updated_at = datetime($created_at)
    WITH c
    OPTIONAL MATCH (c)-[:CONTAINS]->(existing:Message)
    WITH c, coalesce(max(existing.sequence), -1) + 1 AS seq
    CREATE (m:Message {
        id: $id,
        conversation_id: $conversation_id,
        role: $role,
        content: $content,
        tool_use: $tool_use,
        tool_results: $tool_results,
        created_at: datetime($created_at),
        sequence: seq,
        token_usage: $token_usage
    })
    CREATE (c)-[:CONTAINS]->(m)
    RETURN m.sequence AS sequence
    """
    async with neo4j.run(
        query,
        id=msg_id,
        conversation_id=conversation_id,
        role=role,
        content=content,
        tool_use=json.dumps(tool_use) if tool_use else None,
        tool_results=(json.dumps(tool_results) if tool_results else None),
        created_at=now.isoformat(),
        token_usage=(json.dumps(token_usage) if token_usage else None),
    ) as result:
        records = await result.data()

    if not records:
        raise ValueError(f'Conversation not found: {conversation_id}')
    sequence = records[0]['sequence']

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
    conversation_id: str,
    limit: int = 200,
) -> list[models.Message]:
    """Get messages for a conversation ordered by sequence.

    Args:
        conversation_id: UUID of the conversation.
        limit: Maximum number of messages to return.

    Returns:
        List of messages ordered by sequence number.

    """
    query = """
    MATCH (m:Message {conversation_id: $conversation_id})
    RETURN m
    ORDER BY m.sequence ASC
    LIMIT $limit
    """
    messages: list[models.Message] = []
    async with neo4j.run(
        query,
        conversation_id=conversation_id,
        limit=limit,
    ) as result:
        records = await result.data()

    for record in records:
        data = neo4j.convert_neo4j_types(record['m'])
        # Deserialize JSON strings back to Python objects
        for field in ('tool_use', 'tool_results', 'token_usage'):
            if isinstance(data.get(field), str):
                data[field] = json.loads(data[field])
        messages.append(models.Message(**data))
    return messages


async def count_messages(conversation_id: str) -> int:
    """Count messages in a conversation.

    Args:
        conversation_id: UUID of the conversation.

    Returns:
        The number of messages.

    """
    query = """
    MATCH (m:Message {conversation_id: $conversation_id})
    RETURN count(m) AS count
    """
    async with neo4j.run(query, conversation_id=conversation_id) as result:
        records = await result.data()
    return records[0]['count'] if records else 0


async def update_conversation_title(
    conversation_id: str,
    user_email: str,
    title: str,
) -> bool:
    """Update a conversation's title.

    Args:
        conversation_id: UUID of the conversation.
        user_email: Email of the conversation owner.
        title: New title for the conversation.

    Returns:
        True if the conversation was updated.

    """
    query = """
    MATCH (c:Conversation {id: $id, user_email: $user_email})
    SET c.title = $title,
        c.updated_at = datetime()
    RETURN c.id AS id
    """
    async with neo4j.run(
        query,
        id=conversation_id,
        user_email=user_email,
        title=title,
    ) as result:
        records = await result.data()
    return bool(records)


async def archive_conversation(
    conversation_id: str,
    user_email: str,
) -> bool:
    """Archive a conversation.

    Args:
        conversation_id: UUID of the conversation.
        user_email: Email of the conversation owner.

    Returns:
        True if the conversation was archived.

    """
    query = """
    MATCH (c:Conversation {id: $id, user_email: $user_email})
    SET c.is_archived = true,
        c.updated_at = datetime()
    RETURN c.id AS id
    """
    async with neo4j.run(
        query,
        id=conversation_id,
        user_email=user_email,
    ) as result:
        records = await result.data()
    return bool(records)


async def delete_conversation(
    conversation_id: str,
    user_email: str,
) -> bool:
    """Delete a conversation and all its messages.

    Args:
        conversation_id: UUID of the conversation.
        user_email: Email of the conversation owner.

    Returns:
        True if the conversation was deleted.

    """
    query = """
    MATCH (c:Conversation {id: $id, user_email: $user_email})
    OPTIONAL MATCH (c)-[:CONTAINS]->(m:Message)
    DETACH DELETE c, m
    RETURN count(c) AS deleted
    """
    async with neo4j.run(
        query,
        id=conversation_id,
        user_email=user_email,
    ) as result:
        records = await result.data()
    deleted = records[0]['deleted'] if records else 0
    if deleted:
        LOGGER.info(
            'Deleted conversation %s for user %s',
            conversation_id,
            user_email,
        )
    return bool(deleted)
