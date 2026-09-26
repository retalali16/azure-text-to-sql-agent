import os
from dotenv import load_dotenv
from openai import AsyncAzureOpenAI
from schema import DATABASE_SCHEMA

load_dotenv()

# --- Model 1 (default: gpt-4.1-mini) ---
client = AsyncAzureOpenAI(
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
)
DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")

# --- Model 2 (nano) ---
client_nano = AsyncAzureOpenAI(
    api_version=os.getenv("AZURE_OPENAI_NANO_API_VERSION"),
    azure_endpoint=os.getenv("AZURE_OPENAI_NANO_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_NANO_API_KEY"),
)
DEPLOYMENT_NANO = os.getenv("AZURE_OPENAI_NANO_DEPLOYMENT_NAME")


def _resolve(model: str):
    """Map the requested model name to its client + deployment."""
    if model == "model_2":
        return client_nano, DEPLOYMENT_NANO
    return client, DEPLOYMENT  # default / "model_1"


async def generate_sql(question: str, history: list = None, model: str = "model_1") -> str:
    """Ask the LLM to translate a natural-language question into SQL.

    `history` is a list of (sql, error) tuples from previous failed attempts
    in this same request, so the model sees everything it already tried
    instead of only the most recent error.
    """
    active_client, active_deployment = _resolve(model)

    messages = [
        {"role": "system", "content": DATABASE_SCHEMA},
        {"role": "user", "content": f"Write a SQL query to answer this question: {question}"},
    ]

    if history:
        for sql, error in history:
            messages.append({"role": "assistant", "content": sql})
            messages.append({
                "role": "user",
                "content": (
                    f"That query failed with error: {error}. "
                    "Fix it and return ONLY the corrected raw SQL query."
                ),
            })

    response = await active_client.chat.completions.create(
        model=active_deployment,
        messages=messages,
        temperature=0.0,
    )

    return response.choices[0].message.content.strip()


async def generate_answer(question: str, db_result, model: str = "model_1") -> str:
    """Turn raw DB rows into a natural-language answer."""
    active_client, active_deployment = _resolve(model)

    response = await active_client.chat.completions.create(
        model=active_deployment,
        messages=[
            {
                "role": "system",
                "content": "You are a friendly assistant. Answer the user's question "
                            "in natural language using the provided database result.",
            },
            {
                "role": "user",
                "content": f"Question: {question}\nDatabase Result: {db_result}",
            },
        ],
        temperature=0.7,
    )

    return response.choices[0].message.content