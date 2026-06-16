import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

MAX_FILE_SIZE_BYTES = 100 * 1024  # 100KB
MAX_FILES_TO_SCAN = 300
SCANNABLE_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".mjs", ".cjs", ".jsx"}
SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".mypy_cache",
    "dist",
    "build",
    ".next",
}

# (regex_pattern, provider, purpose_hint)
PYTHON_PATTERNS: list[tuple[str, str, str]] = [
    (r"(?:^|\s)(?:import openai|from openai)", "openai", "chat"),
    (r"(?:^|\s)(?:import anthropic|from anthropic)", "anthropic", "chat"),
    (r"(?:^|\s)(?:import ollama|from ollama)", "ollama", "local-inference"),
    (r"(?:^|\s)(?:from langchain|import langchain)", "langchain", "orchestration"),
    (r"(?:^|\s)(?:import litellm|from litellm)", "litellm", "routing"),
    (r"(?:^|\s)(?:import google\.generativeai|from google\.generativeai)", "gemini", "chat"),
    (r"(?:^|\s)(?:import cohere|from cohere)", "cohere", "chat"),
    (r"(?:^|\s)(?:import groq|from groq)", "groq", "chat"),
    (r"(?:^|\s)(?:import mistralai|from mistralai)", "mistral", "chat"),
    (r"(?:^|\s)(?:from transformers|import transformers)", "huggingface", "local-inference"),
    (
        r"(?:^|\s)(?:import sentence_transformers|from sentence_transformers)",
        "huggingface",
        "embeddings",
    ),
    (r"(?:^|\s)(?:import chromadb|from chromadb)", "chromadb", "vector-db"),
    (r"(?:^|\s)(?:import pinecone|from pinecone)", "pinecone", "vector-db"),
    (r"(?:^|\s)(?:import qdrant_client|from qdrant_client)", "qdrant", "vector-db"),
    (r"(?:^|\s)(?:from llama_index|import llama_index)", "llama-index", "rag"),
    (r"(?:^|\s)(?:import crewai|from crewai)", "crewai", "orchestration"),
    (r"(?:^|\s)(?:import autogen|from autogen)", "autogen", "orchestration"),
    (r"(?:^|\s)(?:import dspy|from dspy)", "dspy", "orchestration"),
    (r"OpenAI\(|AsyncOpenAI\(", "openai", "chat"),
    (r"Anthropic\(|AsyncAnthropic\(", "anthropic", "chat"),
]

JS_TS_PATTERNS: list[tuple[str, str, str]] = [
    (r"""(?:require|from)\s+['"]openai['"]""", "openai", "chat"),
    (r"""(?:require|from)\s+['"]@anthropic-ai/sdk['"]""", "anthropic", "chat"),
    (r"""(?:require|from)\s+['"]anthropic['"]""", "anthropic", "chat"),
    (r"""(?:require|from)\s+['"]langchain['"]""", "langchain", "orchestration"),
    (r"""(?:require|from)\s+['"]@langchain""", "langchain", "orchestration"),
    (r"""(?:require|from)\s+['"]ollama['"]""", "ollama", "local-inference"),
    (r"""(?:require|from)\s+['"]@google/generative-ai['"]""", "gemini", "chat"),
    (r"""(?:require|from)\s+['"]groq-sdk['"]""", "groq", "chat"),
    (r"""(?:require|from)\s+['"]cohere-ai['"]""", "cohere", "chat"),
    (r"""(?:require|from)\s+['"]ai['"]""", "vercel-ai-sdk", "chat"),
    (r"""(?:require|from)\s+['"]@ai-sdk/""", "vercel-ai-sdk", "chat"),
    (r"""(?:require|from)\s+['"]@modelcontextprotocol""", "mcp", "tool-use"),
    (r"""(?:require|from)\s+['"]llamaindex['"]""", "llama-index", "rag"),
]

PURPOSE_KEYWORDS: dict[str, str] = {
    "embed": "embeddings",
    "embedding": "embeddings",
    "summarize": "summarization",
    "summarization": "summarization",
    "classify": "classification",
    "codegen": "codegen",
    "ocr": "ocr-cleanup",
    "completion": "chat",
    ".chat": "chat",
    "messages": "chat",
    "retriev": "rag",
    "vector": "embeddings",
}


class LLMDetector:
    """Scans source files for LLM SDK usage patterns.

    Read-only. Does not modify any files.
    Rule-based pattern matching — no AI reasoning.
    """

    def scan_directory(self, target: str) -> list[dict[str, Any]]:
        if not os.path.isdir(target):
            logger.warning("Target not a directory", extra={"target": target})
            return []

        scannable: list[str] = []
        for root, dirs, files in os.walk(target):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for fname in files:
                if os.path.splitext(fname)[1].lower() in SCANNABLE_EXTENSIONS:
                    scannable.append(os.path.join(root, fname))
                    if len(scannable) >= MAX_FILES_TO_SCAN:
                        break
            if len(scannable) >= MAX_FILES_TO_SCAN:
                break

        logger.info(
            "LLM detector scanning",
            extra={"file_count": len(scannable), "target": target},
        )

        # Accumulate: provider → {evidence: list, purpose_hints: set}
        detections: dict[str, dict[str, Any]] = {}

        for file_path in scannable:
            try:
                if os.path.getsize(file_path) > MAX_FILE_SIZE_BYTES:
                    continue
                content = open(file_path).read()
            except OSError:
                continue

            ext = os.path.splitext(file_path)[1].lower()
            patterns = PYTHON_PATTERNS if ext == ".py" else JS_TS_PATTERNS
            rel_path = os.path.relpath(file_path, target)

            for pattern, provider, purpose_hint in patterns:
                if re.search(pattern, content, re.MULTILINE):
                    if provider not in detections:
                        detections[provider] = {"evidence": [], "purpose_hints": set()}
                    entry = detections[provider]
                    evidence_str = f"pattern match in {rel_path}"
                    if evidence_str not in entry["evidence"]:
                        entry["evidence"].append(evidence_str)
                    entry["purpose_hints"].add(purpose_hint)

                    content_lower = content.lower()
                    for kw, purpose in PURPOSE_KEYWORDS.items():
                        if kw in content_lower:
                            entry["purpose_hints"].add(purpose)

        results = []
        for provider, data in detections.items():
            results.append(
                {
                    "provider": provider,
                    "evidence": data["evidence"][:5],
                    "purpose_category": _best_purpose(data["purpose_hints"]),
                    "confidence": "high" if len(data["evidence"]) > 1 else "medium",
                }
            )

        logger.info(
            "LLM detector complete",
            extra={
                "target": target,
                "providers_found": [r["provider"] for r in results],
            },
        )
        return results


def _best_purpose(hints: set[str]) -> str:
    priority = [
        "embeddings",
        "rag",
        "codegen",
        "summarization",
        "chat",
        "vector-db",
        "orchestration",
        "local-inference",
        "ocr-cleanup",
        "classification",
        "tool-use",
    ]
    for p in priority:
        if p in hints:
            return p
    return next(iter(hints), "unknown")
