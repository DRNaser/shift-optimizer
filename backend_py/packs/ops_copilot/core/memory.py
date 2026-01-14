"""
Memory Management Module

Handles episodic memory storage and retrieval for Ops-Copilot.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from uuid import uuid4

from ..observability.tracing import get_logger
from ..observability.metrics import record_memory_latency
import time

logger = get_logger("memory")


async def store_memory(
    conn,
    tenant_id: int,
    thread_id: str,
    memory_type: str,
    content: Dict[str, Any],
    relevance_score: float = 1.0,
    expires_days: Optional[int] = None,
) -> str:
    """
    Store a memory entry.

    Args:
        conn: Database connection
        tenant_id: Tenant ID
        thread_id: Thread ID
        memory_type: Type of memory (PREFERENCE, CORRECTION, CONTEXT, ENTITY, ACTION_HISTORY)
        content: Memory content as JSON
        relevance_score: Initial relevance score (0-1)
        expires_days: Days until expiration (None = permanent)

    Returns:
        Memory ID
    """
    expires_at = None
    if expires_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)

    try:
        with conn.cursor() as cur:
            memory_id = str(uuid4())
            cur.execute(
                """
                INSERT INTO ops.memories (
                    id, tenant_id, thread_id, memory_type, content,
                    relevance_score, expires_at
                ) VALUES (%s::uuid, %s, %s, %s, %s, %s, %s)
                """,
                (memory_id, tenant_id, thread_id, memory_type, content, relevance_score, expires_at),
            )
            conn.commit()

            logger.debug(
                "memory_stored",
                memory_id=memory_id,
                memory_type=memory_type,
                thread_id=thread_id,
            )

            return memory_id

    except Exception as e:
        logger.exception("store_memory_failed", error=str(e))
        conn.rollback()
        raise


async def retrieve_memories(
    conn,
    tenant_id: int,
    thread_id: str,
    memory_types: Optional[List[str]] = None,
    limit: int = 20,
    min_relevance: float = 0.5,
) -> List[Dict[str, Any]]:
    """
    Retrieve relevant memories for a thread.

    Args:
        conn: Database connection
        tenant_id: Tenant ID
        thread_id: Thread ID
        memory_types: Filter by memory types (None = all)
        limit: Maximum memories to retrieve
        min_relevance: Minimum relevance score

    Returns:
        List of memory dicts
    """
    start_time = time.time()

    try:
        with conn.cursor() as cur:
            query = """
                SELECT id, memory_type, content, relevance_score,
                       access_count, created_at
                FROM ops.memories
                WHERE tenant_id = %s
                  AND thread_id = %s
                  AND relevance_score >= %s
                  AND (expires_at IS NULL OR expires_at > NOW())
            """
            params = [tenant_id, thread_id, min_relevance]

            if memory_types:
                query += " AND memory_type = ANY(%s)"
                params.append(memory_types)

            query += " ORDER BY relevance_score DESC, created_at DESC LIMIT %s"
            params.append(limit)

            cur.execute(query, params)
            rows = cur.fetchall()

            memories = [
                {
                    "id": str(row[0]),
                    "memory_type": row[1],
                    "content": row[2],
                    "relevance_score": row[3],
                    "access_count": row[4],
                    "created_at": row[5],
                }
                for row in rows
            ]

            # Update access counts
            if memories:
                memory_ids = [m["id"] for m in memories]
                cur.execute(
                    """
                    UPDATE ops.memories
                    SET access_count = access_count + 1,
                        last_accessed_at = NOW(),
                        updated_at = NOW()
                    WHERE id = ANY(%s::uuid[])
                    """,
                    (memory_ids,),
                )
                conn.commit()

            latency = time.time() - start_time
            record_memory_latency(tenant_id, "retrieve", latency)

            logger.debug(
                "memories_retrieved",
                count=len(memories),
                thread_id=thread_id,
                latency_ms=int(latency * 1000),
            )

            return memories

    except Exception as e:
        logger.exception("retrieve_memories_failed", error=str(e))
        return []


async def decay_memory_relevance(
    conn,
    tenant_id: int,
    thread_id: str,
    decay_factor: float = 0.95,
) -> int:
    """
    Apply decay to memory relevance scores.

    Called periodically to reduce relevance of old memories.

    Args:
        conn: Database connection
        tenant_id: Tenant ID
        thread_id: Thread ID
        decay_factor: Multiplier for relevance (0.95 = 5% decay)

    Returns:
        Number of memories updated
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ops.memories
                SET relevance_score = GREATEST(relevance_score * %s, 0.1),
                    updated_at = NOW()
                WHERE tenant_id = %s
                  AND thread_id = %s
                  AND relevance_score > 0.1
                """,
                (decay_factor, tenant_id, thread_id),
            )
            count = cur.rowcount
            conn.commit()

            if count > 0:
                logger.debug(
                    "memory_decay_applied",
                    count=count,
                    thread_id=thread_id,
                    decay_factor=decay_factor,
                )

            return count

    except Exception as e:
        logger.warning("memory_decay_failed", error=str(e))
        conn.rollback()
        return 0


async def cleanup_expired_memories(
    conn,
    tenant_id: Optional[int] = None,
) -> int:
    """
    Remove expired memories.

    Args:
        conn: Database connection
        tenant_id: Optional tenant filter (None = all tenants)

    Returns:
        Number of memories deleted
    """
    try:
        with conn.cursor() as cur:
            if tenant_id:
                cur.execute(
                    """
                    DELETE FROM ops.memories
                    WHERE tenant_id = %s
                      AND expires_at IS NOT NULL
                      AND expires_at < NOW()
                    """,
                    (tenant_id,),
                )
            else:
                cur.execute(
                    """
                    DELETE FROM ops.memories
                    WHERE expires_at IS NOT NULL
                      AND expires_at < NOW()
                    """
                )

            count = cur.rowcount
            conn.commit()

            if count > 0:
                logger.info(
                    "expired_memories_cleaned",
                    count=count,
                    tenant_id=tenant_id,
                )

            return count

    except Exception as e:
        logger.exception("cleanup_memories_failed", error=str(e))
        conn.rollback()
        return 0


async def get_memory_stats(
    conn,
    tenant_id: int,
    thread_id: str,
) -> Dict[str, Any]:
    """
    Get memory statistics for a thread.

    Args:
        conn: Database connection
        tenant_id: Tenant ID
        thread_id: Thread ID

    Returns:
        Stats dict with counts by type, average relevance, etc.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    memory_type,
                    COUNT(*) as count,
                    AVG(relevance_score) as avg_relevance,
                    SUM(access_count) as total_accesses
                FROM ops.memories
                WHERE tenant_id = %s
                  AND thread_id = %s
                  AND (expires_at IS NULL OR expires_at > NOW())
                GROUP BY memory_type
                """,
                (tenant_id, thread_id),
            )
            rows = cur.fetchall()

            stats = {
                "by_type": {
                    row[0]: {
                        "count": row[1],
                        "avg_relevance": float(row[2]) if row[2] else 0,
                        "total_accesses": row[3],
                    }
                    for row in rows
                },
                "total_count": sum(row[1] for row in rows),
            }

            return stats

    except Exception as e:
        logger.warning("get_memory_stats_failed", error=str(e))
        return {"by_type": {}, "total_count": 0}
