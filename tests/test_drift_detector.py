from memory.drift_detector import DriftDetector


def _payload(
    providers: list[str] | None = None,
    frameworks: list[str] | None = None,
    llm_sdks: list[str] | None = None,
    docker: bool = False,
    ci_cd: list[str] | None = None,
    total_files: int = 100,
    language: str = "python",
) -> dict:
    return {
        "target": "/test",
        "scanned_at": "2026-05-15T19:00:00",
        "scanner_results": {
            "results": {
                "repo_scanner": {
                    "frameworks": frameworks or [],
                    "llm_sdks": llm_sdks or [],
                    "docker": {"present": docker},
                    "ci_cd": ci_cd or [],
                    "primary_language": language,
                    "total_files": total_files,
                }
            }
        },
        "llm_detections": [{"provider": p} for p in (providers or [])],
    }


def test_no_changes_returns_zero() -> None:
    d = DriftDetector()
    prev = _payload(providers=["openai"], frameworks=["fastapi"], llm_sdks=["openai"])
    curr = _payload(providers=["openai"], frameworks=["fastapi"], llm_sdks=["openai"])
    assert d.compare(prev, curr)["change_count"] == 0


def test_new_llm_provider() -> None:
    d = DriftDetector()
    result = d.compare(_payload(), _payload(providers=["anthropic"]))
    assert result["change_count"] == 1
    assert result["changes"][0]["type"] == "llm_provider_added"
    assert result["changes"][0]["value"] == "anthropic"


def test_llm_provider_removed() -> None:
    d = DriftDetector()
    result = d.compare(_payload(providers=["openai"]), _payload())
    assert any(c["type"] == "llm_provider_removed" for c in result["changes"])


def test_framework_added() -> None:
    d = DriftDetector()
    result = d.compare(_payload(), _payload(frameworks=["fastapi"]))
    assert any(
        c["type"] == "framework_added" and c["value"] == "fastapi" for c in result["changes"]
    )


def test_docker_added() -> None:
    d = DriftDetector()
    result = d.compare(_payload(docker=False), _payload(docker=True))
    assert any(c["type"] == "docker_added" for c in result["changes"])


def test_language_change() -> None:
    d = DriftDetector()
    result = d.compare(_payload(language="python"), _payload(language="javascript"))
    assert any(c["type"] == "language_changed" for c in result["changes"])


def test_significant_file_count_change() -> None:
    d = DriftDetector()
    result = d.compare(_payload(total_files=100), _payload(total_files=200))
    assert any(c["type"] == "file_count_changed" for c in result["changes"])


def test_small_file_count_change_ignored() -> None:
    d = DriftDetector()
    result = d.compare(_payload(total_files=100), _payload(total_files=110))
    assert not any(c["type"] == "file_count_changed" for c in result["changes"])


def test_human_readable_populated() -> None:
    d = DriftDetector()
    result = d.compare(_payload(), _payload(providers=["openai"]))
    assert len(result["human_readable"]) > 0


def test_summary_text_with_changes() -> None:
    d = DriftDetector()
    result = d.compare(_payload(), _payload(docker=True))
    assert "1" in result["summary"]


def test_summary_text_no_changes() -> None:
    d = DriftDetector()
    result = d.compare(_payload(), _payload())
    assert "No changes" in result["summary"]
