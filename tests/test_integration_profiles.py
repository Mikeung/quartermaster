"""Tests for integrations/profiles.py — integration profile registry."""

from __future__ import annotations

from integrations.profiles import (
    get_profile,
    list_profiles,
    profile_names,
)


class TestProfileRegistry:
    def test_list_profiles_nonempty(self):
        assert len(list_profiles()) >= 7

    def test_all_expected_stacks_present(self):
        names = profile_names()
        for stack in ("fastapi", "n8n", "langchain", "openai_sdk", "anthropic_sdk", "celery", "ocr_pipeline"):
            assert stack in names, f"Expected stack '{stack}' in profiles"

    def test_get_profile_returns_correct(self):
        p = get_profile("fastapi")
        assert p is not None
        assert p.stack == "fastapi"

    def test_get_profile_unknown_returns_none(self):
        assert get_profile("nonexistent-stack") is None

    def test_get_profile_case_insensitive(self):
        p = get_profile("FASTAPI")
        assert p is not None


class TestProfileAttributes:
    def test_fastapi_profile(self):
        p = get_profile("fastapi")
        assert p.recommended_workflow_prefix == "api"
        assert p.batching_recommended is False
        assert "endpoint" in p.recommended_metadata_keys

    def test_langchain_profile_recommends_batching(self):
        p = get_profile("langchain")
        assert p.batching_recommended is True
        assert p.suggested_batch_size > 1

    def test_celery_profile_recommends_batching(self):
        p = get_profile("celery")
        assert p.batching_recommended is True
        assert p.suggested_max_events_per_hour >= 1000

    def test_ocr_pipeline_extended_retention(self):
        p = get_profile("ocr_pipeline")
        assert p.suggested_retention_days >= 60

    def test_all_profiles_have_cautions(self):
        for p in list_profiles():
            assert len(p.cautions) > 0, f"Profile '{p.stack}' has no cautions"

    def test_all_profiles_have_example_event(self):
        for p in list_profiles():
            assert p.example_event, f"Profile '{p.stack}' has no example event"
            assert "provider" in p.example_event
            assert "workflow" in p.example_event

    def test_example_events_have_no_forbidden_fields(self):
        forbidden = {"prompt", "response", "content", "messages", "text"}
        for p in list_profiles():
            keys = set(p.example_event.keys())
            overlap = keys & forbidden
            assert not overlap, f"Profile '{p.stack}' example has forbidden fields: {overlap}"


class TestProfileToDict:
    def test_to_dict_serializable(self):
        p = get_profile("openai_sdk")
        d = p.to_dict()
        assert d["stack"] == "openai_sdk"
        assert "required_fields" in d
        assert "recommended_metadata_keys" in d
        assert "cautions" in d
        assert isinstance(d["cautions"], list)

    def test_to_dict_has_all_keys(self):
        p = get_profile("anthropic_sdk")
        d = p.to_dict()
        required_keys = [
            "stack", "display_name", "description", "recommended_workflow_prefix",
            "required_fields", "batching_recommended", "suggested_retention_days",
            "cautions", "example_event",
        ]
        for k in required_keys:
            assert k in d, f"Missing key '{k}' in to_dict output"
