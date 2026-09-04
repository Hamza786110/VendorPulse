"""
contracts/chains.py

"""

from typing import cast

from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from contracts.models import ExtractedContractFields
from dotenv import load_dotenv
load_dotenv()

model = ChatGroq(model="openai/gpt-oss-120b")


EXTRACTION_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a precise contract-analysis assistant. Extract only what is "
            "explicitly stated or clearly implied in the contract text below. "
            "Never guess or fabricate values — leave a field empty/null if it's "
            "not stated in the text.",
        ),
        (
            "human",
            "Contract text:\n\n{contract_text}",
        ),
    ]
)


def build_extraction_chain():
    """
    Returns a runnable chain: prompt -> Groq LLM bound to structured output.
    LangChain 1.x's `with_structured_output` handles the schema/tool-calling
    plumbing for us — no manual output parser or format instructions needed.
    Usage:
        chain = build_extraction_chain()
        result: ExtractedContractFields = chain.invoke({"contract_text": raw_text})
    """
    llm = model.with_structured_output(ExtractedContractFields)
    return EXTRACTION_PROMPT | llm


def extract_contract_fields(contract_text: str) -> ExtractedContractFields:
    """
    Convenience wrapper used by the route handler.
    Truncates very long contracts to keep within context/token limits —
    for a portfolio demo this is fine; production would chunk + summarize.
    """
    MAX_CHARS = 15000
    text = contract_text[:MAX_CHARS]

    chain = build_extraction_chain()
    result = chain.invoke({"contract_text": text})
    return cast(ExtractedContractFields, result)