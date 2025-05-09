"""Langserve application."""

import os
import uvicorn
from typing import Optional
from fastapi import FastAPI
from langchain.schema.runnable import RunnableLambda
from langserve import CustomUserType, add_routes
from functions import answer, search_answer, get_summary

# Define custom request classes


class AskRequest(CustomUserType):
    """Request with a question to LLM model."""

    question: str


class SearchRequest(CustomUserType):
    """Request with a question to LLM model based on documents provided."""

    question: str
    bucket: str
    blob: Optional[str] = None


class SummarizeRequest(CustomUserType):
    """Request of summarizing the documents provided."""

    bucket: str
    blob: Optional[str] = None


# Define functions for handling certain types of requests


def _ask(request: AskRequest) -> str:
    """Handle AskRequest by providing it to answer() function."""
    return answer(request.question)


def _search(request: SearchRequest) -> str:
    """Handle SearchRequest by providing it to search_answer() function."""
    return search_answer(
        bucket=request.bucket, blob=request.blob, question=request.question
    )


def _summarize(request: SummarizeRequest) -> str:
    """Handle SummarizeRequest by providing it to get_summary() function."""
    return get_summary(bucket=request.bucket, blob=request.blob)


# Create the FastAPI app and add routing

app = FastAPI(
    title="LangChain Server",
    version="1.0",
    description="Cloud Run service to communicate with LLMs using LangChain and langserve",
)

add_routes(
    app,
    RunnableLambda(_ask).with_types(input_type=AskRequest),
    config_keys=["configurable"],
    path="/ask",
)

add_routes(
    app,
    RunnableLambda(_search).with_types(input_type=SearchRequest),
    config_keys=["configurable"],
    path="/search",
)

add_routes(
    app,
    RunnableLambda(_summarize).with_types(input_type=SearchRequest),
    config_keys=["configurable"],
    path="/summarize",
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
