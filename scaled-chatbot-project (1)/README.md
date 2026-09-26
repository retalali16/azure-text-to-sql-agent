# Database AI Agent — Scaled Architecture

Text-to-SQL chatbot (Azure OpenAI + PostgreSQL) rebuilt for scale:
async I/O, connection pooling, SQL guardrails, Redis caching, and
horizontal scaling behind nginx.

## Embedding model (semantic cache)

The cache now has two layers: an exact-match cache (fast, catches identical
repeated questions) and a semantic cache (catches paraphrased questions like
"top customers" vs "best customers" using embedding similarity).

You need a **separate embedding model deployment** in Azure OpenAI Studio
(e.g. `text-embedding-3-small`) — it's a different model type than the chat
deployment (`gpt-4.1-mini`) and needs its own deployment name in `.env`:
`AZURE_OPENAI_EMBEDDING_DEPLOYMENT`.

The similarity threshold (`SEMANTIC_SIMILARITY_THRESHOLD` in `cache.py`,
default `0.90`) controls how close two questions need to be to count as a
cache hit — lower it if too many distinct questions are being treated as
the same, raise it if paraphrases aren't matching.

## Security first

1. Copy `backend/.env.example` to `backend/.env` and fill in your real
   credentials. `.env` is gitignored — never commit it.
2. If any database password was ever shared or committed before, rotate
   it now in Railway before doing anything else.
3. `DATABASE_URL` must use the `asyncpg` driver:
   `postgresql+asyncpg://user:password@host:port/dbname`

## Run locally without Docker (single instance)

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```
Open http://127.0.0.1:8000/docs to test the `/chat` endpoint.
(Redis caching needs a local Redis instance running, or comment out
the cache calls in `main.py` for a quick local test.)

## Run at scale with Docker Compose (3 app replicas + Redis + nginx)

`deploy.replicas` in `docker-compose.yml` is a Swarm-only setting, so on
plain Docker Compose scale explicitly:

```bash
docker compose up --build --scale app=3
```

Requests now go through nginx on port 80 and get load-balanced across
the 3 app containers:

```bash
curl -X POST http://localhost/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "Who are the top customers?"}'
```

## Load testing (proves it handles concurrent traffic)

```bash
pip install locust
locust -f locustfile.py --host http://localhost
```
Open http://localhost:8089, set the number of users (try 50 → 200 → 500)
and spawn rate, then compare:
- Response time with 1 replica vs 3 replicas
- Response time with cold cache vs warm cache
- Requests/sec and failure rate as load increases

Record these numbers — they're the evidence of "scale" even while the
underlying dataset (Chinook) stays the same size.

## What's included

| File | Purpose |
|---|---|
| `backend/main.py` | FastAPI app, `/chat` endpoint, orchestrates the pipeline |
| `backend/db.py` | Async engine, connection pooling, SQL guardrails (SELECT-only, row limit) |
| `backend/llm.py` | Async Azure OpenAI calls: SQL generation + one self-correction pass, then answer generation |
| `backend/cache.py` | Exact-match + semantic (embedding-based) caching |
| `backend/embeddings.py` | Generates question embeddings via Azure OpenAI |
| `backend/schema.py` | Database schema fed to the LLM |
| `backend/Dockerfile` | Container image for the app |
| `docker-compose.yml` | Orchestrates 3 app replicas + Redis + nginx |
| `nginx.conf` | Load balancer distributing requests across replicas |
| `locustfile.py` | Load test simulating concurrent users |
