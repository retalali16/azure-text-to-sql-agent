from dotenv import load_dotenv
load_dotenv()  # no-op in Docker (env vars come from env_file instead)

from enum import Enum
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from db import execute_sql
from llm import generate_sql, generate_answer
from cache import (
    get_cached_answer,
    set_cached_answer,
    get_semantic_cached_answer,
    set_semantic_cached_answer,
    get_all_semantic_cached_questions,
)

app = FastAPI(
    title="Database AI Agent API",
    description="Chat with a PostgreSQL database using Azure OpenAI (text-to-SQL).",
    version="2.0",
)

FAILURE_MESSAGE = "Sorry, I couldn't answer that question."
MAX_SQL_ATTEMPTS = 4  # 1 initial try + 3 self-correction retries, each with full history


class ModelChoice(str, Enum):
    model_1 = "model_1"  # gpt-4.1-mini
    model_2 = "model_2"  # gpt-4.1-nano


class QueryRequest(BaseModel):
    question: str
    model: ModelChoice = ModelChoice.model_1  # shows as a dropdown in Swagger


class QueryResponse(BaseModel):
    answer: str
    cached: bool = False
    model_used: str = "model_1"


@app.get("/")
async def root():
    return {"message": "Database AI Agent API is running."}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/cached-questions")
async def cached_questions(model: ModelChoice = ModelChoice.model_1):
    return await get_all_semantic_cached_questions(model=model.value)


async def chat_with_database(question: str, model: str) -> str:
    history = []  # list of (sql, error) tuples for every failed attempt so far

    for attempt in range(MAX_SQL_ATTEMPTS):
        sql_query = await generate_sql(question, history=history, model=model)
        rows, error = await execute_sql(sql_query)

        if not error:
            # Success — turn the raw rows into a natural-language answer
            return await generate_answer(question, rows, model=model)

        # Failed — remember it and let the model see the full history next try
        history.append((sql_query, error))

    # Every attempt failed
    return FAILURE_MESSAGE


@app.post("/chat", response_model=QueryResponse)
async def chat_endpoint(request: QueryRequest):
    question = request.question.strip()
    model = request.model.value

    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    # 1. Exact match — cheapest, catches identical repeated questions
    #    (cache key includes the model, so model_1 and model_2 never share answers)
    cached = await get_cached_answer(question, model=model)
    if cached:
        return QueryResponse(answer=cached, cached=True, model_used=model)

    # 2. Semantic match — catches paraphrased/reworded questions
    semantic_cached = await get_semantic_cached_answer(question, model=model)
    if semantic_cached:
        await set_cached_answer(question, semantic_cached, model=model)  # promote to exact cache too
        return QueryResponse(answer=semantic_cached, cached=True, model_used=model)

    # 3. Full pipeline: nothing cached, ask the LLM + query the DB
    answer = await chat_with_database(question, model=model)

    # Don't cache failures — a question that failed once might succeed on a
    # later attempt (transient DB/LLM hiccup), and caching the failure would
    # lock that question into "couldn't answer" for the full TTL.
    if answer != FAILURE_MESSAGE:
        await set_cached_answer(question, answer, model=model)
        await set_semantic_cached_answer(question, answer, model=model)

    return QueryResponse(answer=answer, cached=False, model_used=model)