import os
import tempfile

from llm_intelligence.detector import LLMDetector


def _write(tmpdir: str, name: str, content: str) -> None:
    with open(os.path.join(tmpdir, name), "w") as f:
        f.write(content)


def test_detects_anthropic_python_import() -> None:
    with tempfile.TemporaryDirectory() as d:
        _write(d, "main.py", "import anthropic\nclient = anthropic.Anthropic()\n")
        result = LLMDetector().scan_directory(d)
    assert any(r["provider"] == "anthropic" for r in result)


def test_detects_openai_python_from_import() -> None:
    with tempfile.TemporaryDirectory() as d:
        _write(d, "app.py", "from openai import OpenAI\nclient = OpenAI()\n")
        result = LLMDetector().scan_directory(d)
    assert any(r["provider"] == "openai" for r in result)


def test_detects_langchain() -> None:
    with tempfile.TemporaryDirectory() as d:
        _write(d, "chain.py", "from langchain.chat_models import ChatOpenAI\n")
        result = LLMDetector().scan_directory(d)
    assert any(r["provider"] == "langchain" for r in result)


def test_no_detections_on_plain_code() -> None:
    with tempfile.TemporaryDirectory() as d:
        _write(d, "main.py", "def add(a, b):\n    return a + b\n")
        result = LLMDetector().scan_directory(d)
    assert result == []


def test_handles_missing_target() -> None:
    result = LLMDetector().scan_directory("/nonexistent/path/xyz")
    assert result == []


def test_returns_evidence_list() -> None:
    with tempfile.TemporaryDirectory() as d:
        _write(d, "worker.py", "import anthropic\n")
        result = LLMDetector().scan_directory(d)
    anthropic = next(r for r in result if r["provider"] == "anthropic")
    assert len(anthropic["evidence"]) >= 1
    assert "worker.py" in anthropic["evidence"][0]


def test_confidence_medium_for_single_match() -> None:
    with tempfile.TemporaryDirectory() as d:
        _write(d, "a.py", "import anthropic\n")
        result = LLMDetector().scan_directory(d)
    anthropic = next(r for r in result if r["provider"] == "anthropic")
    assert anthropic["confidence"] == "medium"


def test_confidence_high_for_multiple_files() -> None:
    with tempfile.TemporaryDirectory() as d:
        _write(d, "a.py", "import anthropic\n")
        _write(d, "b.py", "from anthropic import Anthropic\n")
        result = LLMDetector().scan_directory(d)
    anthropic = next(r for r in result if r["provider"] == "anthropic")
    assert anthropic["confidence"] == "high"
