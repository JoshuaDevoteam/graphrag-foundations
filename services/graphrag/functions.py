"""Utility functions for Langserve application."""

import re
import os
from typing import List

from langchain import hub
from langchain.llms import VertexAI
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain, SimpleSequentialChain
from langchain.chains.summarize import load_summarize_chain
from langchain.document_loaders import GCSFileLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.embeddings import VertexAIEmbeddings
from langchain.vectorstores import Chroma
from langchain.schema import StrOutputParser
from langchain.schema.runnable import RunnablePassthrough
from langchain_core.documents.base import Document

PROJECT_ID = os.environ.get("PROJECT_ID")


def create_llm_chain(
    template: str,
    model_name: str = "text-bison@001",
    max_output_tokens: int = 256,
    temperature: float = 0.1,
    top_p: float = 0.9,
    top_k: float = 40,
) -> LLMChain:
    """Create a LLMChain object from Vertex AI LLM model based on template and model configuration provided."""
    pattern = r"\{([^}]+)\}"
    input_variables = re.findall(pattern, template)
    if input_variables == []:
        raise ValueError("No input variables found in template.")

    llm = VertexAI(
        model_name=model_name,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
        top_p=top_p,
        top_k=top_k,
    )

    prompt = PromptTemplate(template=template, input_variables=input_variables)
    llm_chain = LLMChain(llm=llm, prompt=prompt)
    return llm_chain


def process_llm_chain_list(llm_chain_list: List[LLMChain]) -> SimpleSequentialChain:
    """Create a SimpleSequentialChain object from a list of LLMChain objects."""
    seq_chain = SimpleSequentialChain(chains=llm_chain_list)
    return seq_chain


def answer(question: str) -> str:
    """Answer a question using a simple Vertex AI LLM model."""
    llm = create_llm_chain("Reply to the following: {text}")
    seq_chain = process_llm_chain_list([llm])
    return seq_chain.run(question)


def load_documents(bucket: str, blob: str) -> List[Document]:
    """Load documents from a GCS bucket and blob provided."""
    loader = GCSFileLoader(project_name=PROJECT_ID, bucket=bucket, blob=blob)
    documents = loader.load()
    return documents


def split_text(
    documents: List[Document],
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    add_start_index: bool = True,
) -> List[Document]:
    """Split text into chunks of specified size."""
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        add_start_index=add_start_index,
    )
    all_splits = text_splitter.split_documents(documents)
    return all_splits


def create_vector_store(splits: List[Document]) -> Chroma:
    """Create a Chroma vector store from a list of documents (or splits)."""
    vectorstore = Chroma.from_documents(
        documents=splits, embedding=VertexAIEmbeddings()
    )
    return vectorstore


def create_retriever(
    vectorstore: Chroma, search_type: str = "similarity", search_kwargs_k: int = 6
) -> Chroma:
    """Create a retriever."""
    retriever = vectorstore.as_retriever(
        search_type=search_type, search_kwargs={"k": search_kwargs_k}
    )
    return retriever


def retrieve_docs(retriever: Chroma, query: str) -> List[Document]:
    """Retrieve documents from a retriever based on a query."""
    docs = retriever.get_relevant_documents(query)
    return docs


def summarize_docs(
    llm: VertexAI, documents: List[Document], chain_type: str = "refine"
):
    """Summarize a list of documents using an LLM."""
    chain = load_summarize_chain(llm, chain_type=chain_type)
    summary = chain.run(documents)
    return summary


def format_docs(docs: List[Document]) -> str:
    """Format a list of documents into a single string."""
    return "\n\n".join(doc.page_content for doc in docs)


def get_summary(bucket: str, blob: str) -> str:
    """Get summary of a document using an LLM."""
    documents = load_documents(bucket=bucket, blob=blob)
    splits = split_text(documents)
    llm = VertexAI(temperature=0)
    chain = load_summarize_chain(llm, chain_type="stuff")
    return chain.run(splits)


def search_answer(bucket: str, blob: str, question: str) -> str:
    """Answer a question using an LLM."""
    documents = load_documents(bucket=bucket, blob=blob)
    splits = split_text(documents)
    vectorstore = create_vector_store(splits)
    retriever = create_retriever(vectorstore)
    llm = VertexAI(temperature=0)
    prompt = hub.pull("rlm/rag-prompt")
    rag_chain = (
        {"context": retriever | format_docs, "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )
    output = ""
    for chunk in rag_chain.stream(question):
        output += chunk

    return output
