import os
import re
import json
import hashlib
import numpy as np
import redis.asyncio as redis

from embeddings import get_embedding

redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "redis"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    decode_responses=True,
)

CACHE_TTL_SECONDS = 3600  # 1 hour

# ---------------------------------------------------------------------------
# Exact-match cache (fast, cheap, catches identical repeated questions)
# ---------------------------------------------------------------------------

def make_cache_key(question: str, model: str = "model_1") -> str:
    # Include the model in the key so each model gets its own cached answer —
    # otherwise testing model_2 could silently return model_1's cached result.
    raw = f"{model}:{question.strip().lower()}"
    return "chat:" + hashlib.md5(raw.encode()).hexdigest()


async def get_cached_answer(question: str, model: str = "model_1"):
    try:
        return await redis_client.get(make_cache_key(question, model))
    except Exception:
        # If Redis is down, fail open (no cache) instead of crashing the request.
        return None


async def set_cached_answer(question: str, answer: str, model: str = "model_1"):
    try:
        await redis_client.setex(make_cache_key(question, model), CACHE_TTL_SECONDS, answer)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Semantic cache (catches paraphrased questions using embedding similarity)
# ---------------------------------------------------------------------------

SEMANTIC_CACHE_KEY_PREFIX = "semantic_cache"  # one Redis hash per model: semantic_cache:model_1, semantic_cache:model_2
SEMANTIC_MAX_ENTRIES = 500                    # cap so the brute-force scan below stays cheap
SEMANTIC_SIMILARITY_THRESHOLD = 0.90          # tune based on false-positive rate you observe


def _semantic_key(model: str) -> str:
    return f"{SEMANTIC_CACHE_KEY_PREFIX}:{model}"


def _contains_number_or_date(question: str) -> bool:
    """Heuristic: does this question reference a specific number/year/date?

    Questions like "revenue in 2023" vs "revenue in 2024" are textually very
    similar (high cosine similarity) but need completely different answers.
    Safer to skip the fuzzy semantic match here and rely on exact-match
    caching only for these — a false positive would be a silently wrong
    answer with no error signal.
    """
    return bool(re.search(r"\d", question))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    a, b = np.array(a), np.array(b)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


async def get_semantic_cached_answer(question: str, model: str = "model_1"):
    """Brute-force similarity search over cached entries.

    Fine at hundreds of entries; if the cache grows much larger, move to
    a real vector index (e.g. Redis Stack / RediSearch with HNSW) instead
    of scanning every entry.
    """
    if _contains_number_or_date(question):
        return None

    try:
        key = _semantic_key(model)
        entries = await redis_client.hgetall(key)
        if not entries:
            return None

        query_embedding = await get_embedding(question)

        best_answer, best_score = None, 0.0
        for raw in entries.values():
            entry = json.loads(raw)
            score = _cosine_similarity(query_embedding, entry["embedding"])
            if score > best_score:
                best_score, best_answer = score, entry["answer"]

        if best_score >= SEMANTIC_SIMILARITY_THRESHOLD:
            return best_answer
        return None
    except Exception:
        # Embedding call failed, Redis down, malformed entry, etc. — fail open.
        return None


async def set_semantic_cached_answer(question: str, answer: str, model: str = "model_1"):
    if _contains_number_or_date(question):
        return

    try:
        key = _semantic_key(model)
        embedding = await get_embedding(question)
        entry_id = hashlib.md5(question.strip().lower().encode()).hexdigest()
        entry = json.dumps({"question": question, "embedding": embedding, "answer": answer})

        await redis_client.hset(key, entry_id, entry)

        # Evict oldest-ish entries once this model's cache grows past the cap
        # (HRANDFIELD keeps this cheap; exact LRU isn't needed here).
        if await redis_client.hlen(key) > SEMANTIC_MAX_ENTRIES:
            stale_field = await redis_client.hrandfield(key)
            if stale_field:
                await redis_client.hdel(key, stale_field)
    except Exception as e:
        print("SET SEMANTIC CACHE ERROR:", repr(e))


# ---------------------------------------------------------------------------
# Debug/demo helper: list everything currently in the semantic cache
# ---------------------------------------------------------------------------

async def get_all_semantic_cached_questions(model: str = "model_1"):
    try:
        key = _semantic_key(model)
        entries = await redis_client.hgetall(key)
        results = []
        for raw in entries.values():
            entry = json.loads(raw)
            results.append({
                "question": entry.get("question"),
                "answer": entry.get("answer"),
            })
        return results
    except Exception:
        return []