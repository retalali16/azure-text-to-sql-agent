"""
Database AI Agent — Streamlit front-end
----------------------------------------
Single-file app: no separate FastAPI backend. This file talks directly to
db.py / llm.py / cache.py / embeddings.py in the backend/ folder.

Deploy target: Streamlit Community Cloud.
Secrets (API keys, DB URL, etc.) are read from environment variables —
on Streamlit Cloud, set them under App settings -> Secrets (TOML format),
which Streamlit exposes as environment variables automatically.
"""

import os
import sys
import asyncio

import streamlit as st

# Make backend/ importable (db.py, llm.py, cache.py, embeddings.py live there)
sys.path.append(os.path.join(os.path.dirname(__file__), "backend"))

from db import execute_sql
from llm import generate_sql, generate_answer
from cache import (
    get_cached_answer,
    set_cached_answer,
    get_semantic_cached_answer,
    set_semantic_cached_answer,
    get_all_semantic_cached_questions,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

FAILURE_MESSAGE = "Sorry, I couldn't answer that question."
MAX_SQL_ATTEMPTS = 4

MODEL_LABELS = {
    "model_1": "GPT-4.1 mini",
    "model_2": "GPT-4.1 nano",
}

st.set_page_config(
    page_title="Database AI Agent",
    page_icon="🗄️",
    layout="centered",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
        .block-container { padding-top: 2rem; max-width: 780px; }
        .app-subtitle { color: #6b7280; font-size: 0.95rem; margin-top: -0.6rem; }
        .cache-badge {
            display: inline-block;
            padding: 0.1rem 0.55rem;
            border-radius: 999px;
            font-size: 0.75rem;
            font-weight: 600;
            background: #ecfdf5;
            color: #047857;
            border: 1px solid #a7f3d0;
        }
        .model-badge {
            display: inline-block;
            padding: 0.1rem 0.55rem;
            border-radius: 999px;
            font-size: 0.75rem;
            font-weight: 600;
            background: #eff6ff;
            color: #1d4ed8;
            border: 1px solid #bfdbfe;
            margin-left: 0.4rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Async pipeline (mirrors backend/main.py logic, model-aware caching)
# ---------------------------------------------------------------------------


async def chat_with_database(question: str, model: str) -> str:
    history = []
    for _ in range(MAX_SQL_ATTEMPTS):
        sql_query = await generate_sql(question, history=history, model=model)
        rows, error = await execute_sql(sql_query)
        if not error:
            return await generate_answer(question, rows, model=model)
        history.append((sql_query, error))
    return FAILURE_MESSAGE


async def answer_question(question: str, model: str):
    """Returns (answer, was_cached)."""
    cached = await get_cached_answer(question, model=model)
    if cached:
        return cached, True

    semantic_cached = await get_semantic_cached_answer(question, model=model)
    if semantic_cached:
        await set_cached_answer(question, semantic_cached, model=model)
        return semantic_cached, True

    answer = await chat_with_database(question, model)
    if answer != FAILURE_MESSAGE:
        await set_cached_answer(question, answer, model=model)
        await set_semantic_cached_answer(question, answer, model=model)
    return answer, False


def run_async(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("### ⚙️ Settings")

    model_key = st.selectbox(
        "Model",
        options=list(MODEL_LABELS.keys()),
        format_func=lambda k: MODEL_LABELS[k],
        help="Choose which Azure OpenAI deployment answers your question.",
    )

    st.divider()

    with st.expander("📦 Cached questions", expanded=False):
        st.caption(f"Semantic cache for **{MODEL_LABELS[model_key]}**")
        if st.button("Refresh cache list", use_container_width=True):
            st.session_state["_refresh_cache"] = True

        try:
            cached_items = run_async(get_all_semantic_cached_questions(model=model_key))
        except Exception:
            cached_items = []

        if cached_items:
            for item in cached_items:
                st.markdown(f"**Q:** {item['question']}")
                st.markdown(f"**A:** {item['answer']}")
                st.markdown("---")
        else:
            st.caption("No cached questions yet for this model.")

    st.divider()
    if st.button("🗑️ Clear conversation", use_container_width=True):
        st.session_state.history = []
        st.rerun()

# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------

st.title("🗄️ Database AI Agent")
st.markdown(
    '<p class="app-subtitle">Ask questions in plain English — answers are generated '
    "from your PostgreSQL database via Azure OpenAI.</p>",
    unsafe_allow_html=True,
)
st.write("")

if "history" not in st.session_state:
    st.session_state.history = []  # list of dicts: role, content, cached, model

for message in st.session_state.history:
    with st.chat_message(message["role"]):
        st.write(message["content"])
        if message["role"] == "assistant":
            badges = f'<span class="model-badge">{MODEL_LABELS.get(message.get("model"), "")}</span>'
            if message.get("cached"):
                badges += ' <span class="cache-badge">⚡ from cache</span>'
            st.markdown(badges, unsafe_allow_html=True)

question = st.chat_input("Ask a question about the database...")

if question:
    st.session_state.history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        with st.spinner(f"Thinking with {MODEL_LABELS[model_key]}..."):
            try:
                answer, was_cached = run_async(answer_question(question, model_key))
            except Exception as e:
                answer, was_cached = f"⚠️ Something went wrong: {e}", False

        st.write(answer)
        badges = f'<span class="model-badge">{MODEL_LABELS[model_key]}</span>'
        if was_cached:
            badges += ' <span class="cache-badge">⚡ from cache</span>'
        st.markdown(badges, unsafe_allow_html=True)

    st.session_state.history.append(
        {"role": "assistant", "content": answer, "cached": was_cached, "model": model_key}
    )
