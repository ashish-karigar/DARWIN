import os

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama

from app.llm.usage import groq_usage_callback

load_dotenv()

def create_primary_model(
    tools: list | None = None,
    *,
    reasoning_effort: str = "medium",
):
    model = ChatGroq(
        model="openai/gpt-oss-120b",
        temperature=0,
        callbacks=[groq_usage_callback],
        reasoning_effort=reasoning_effort,
        # GPT-OSS uses this budget for reasoning as well as visible output.
        # A small value can therefore produce empty or cut-off responses.
        max_tokens=1_200,
        # DARWIN owns retry and provider failover. Retrying a daily
        # quota error inside the SDK only wastes time and trace space.
        max_retries=0,
    )

    return (
        model.bind_tools(tools, parallel_tool_calls=False)
        if tools
        else model
    )

def create_fallback_model(tools: list | None = None):
    model = ChatOllama(
        model="qwen3:14b",
        reasoning=False,
        temperature=0.1,
    )

    return (
        model.bind_tools(tools)
        if tools
        else model
    )


def create_groq_verifier_model():
    """Creates the fast Groq judge used to verify generated answers.

    Deliberately a different model family than the generator
    (openai/gpt-oss-120b) so verification stays an independent check
    rather than the same model grading its own homework. Groq's
    generation speed is what makes this worth doing: a local Ollama
    judge doing the same claim-by-claim check runs 15-20s slower on
    typical hardware, so this is the primary path and the local model
    (create_local_verifier_model) is only the fallback.
    """

    return ChatGroq(
        model=os.getenv(
            "DARWIN_GROQ_VERIFIER_MODEL",
            "qwen/qwen3.8-27b",
        ),
        temperature=0,
        callbacks=[groq_usage_callback],
        max_tokens=int(
            os.getenv("DARWIN_GROQ_VERIFIER_MAX_TOKENS", "900")
        ),
        # DARWIN owns retry and provider failover (see StructuredModelRunner);
        # retrying here would just delay the fall back to the local model.
        max_retries=0,
    )


def create_local_judge_model(
    *,
    max_tokens: int | None = None,
    timeout_seconds: float | None = None,
):
    """Creates the smaller local model used for bounded RAG decisions."""

    return ChatOllama(
        model=os.getenv(
            "DARWIN_LOCAL_JUDGE_MODEL",
            "qwen3:8b",
        ),
        reasoning=False,
        temperature=0,
        num_predict=(
            max_tokens
            if max_tokens is not None
            else int(
                os.getenv("DARWIN_LOCAL_JUDGE_MAX_TOKENS", "450")
            )
        ),
        keep_alive="30m",
        client_kwargs={
            "timeout": (
                timeout_seconds
                if timeout_seconds is not None
                else float(
                    os.getenv(
                        "DARWIN_LOCAL_JUDGE_TIMEOUT_SECONDS",
                        "30",
                    )
                )
            )
        },
    )


def create_local_verifier_model():
    """Creates a judge with enough output room for multi-claim JSON."""

    return create_local_judge_model(
        max_tokens=int(
            os.getenv("DARWIN_LOCAL_VERIFIER_MAX_TOKENS", "900")
        ),
        timeout_seconds=float(
            os.getenv("DARWIN_LOCAL_VERIFIER_TIMEOUT_SECONDS", "45")
        ),
    )
