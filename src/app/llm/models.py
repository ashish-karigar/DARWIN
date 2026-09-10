from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama

load_dotenv()

def create_primary_model(tools: list | None= None):
    model = ChatGroq(
        model="openai/gpt-oss-120b",
        temperature=0,
        # GPT-OSS uses this budget for reasoning as well as visible output.
        # A small value can therefore produce empty or cut-off responses.
        max_tokens=1_200,
        max_retries=2,
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
