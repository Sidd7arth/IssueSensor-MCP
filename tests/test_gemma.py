"""Unit tests for repromcp.gemma module (mocked, no real API keys or network)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from repromcp.gemma import (
    DEFAULT_GEMMA_MODEL,
    call_gemma_analysis,
    get_configured_gemma_model,
    parse_gemma_response,
)

SAMPLE_VALID_ANALYSIS = {
    "visual_observations": ["Checkout total displays 120.00 instead of 80.00."],
    "likely_root_cause": "The discount calculation adds the discount percentage instead of subtracting it.",
    "confidence": "high",
    "supporting_evidence": [
        {"file": "discounts.py", "line": 6, "observation": "return round(price * (1 + percent / 100), 2)"}
    ],
    "reproduction_steps": ["Call calculate_discount(100, 20).", "Observe result is 120.00."],
    "suggested_regression_test": "def test_twenty_percent_discount(): assert calculate_discount(100, 20) == 80.0",
    "unknowns_and_limitations": ["Assumes prices and percentages are positive non-zero values."],
}


def test_get_configured_gemma_model(monkeypatch):
    monkeypatch.delenv("GEMMA_MODEL", raising=False)
    assert get_configured_gemma_model() == DEFAULT_GEMMA_MODEL

    monkeypatch.setenv("GEMMA_MODEL", "gemma-4-31b-it")
    assert get_configured_gemma_model() == "gemma-4-31b-it"

    # Reject Gemini-branded model substitution
    monkeypatch.setenv("GEMMA_MODEL", "gemini-1.5-pro")
    with pytest.raises(ValueError, match="not a permitted Gemma 4 model"):
        get_configured_gemma_model()

    # Reject arbitrary third-party models
    monkeypatch.setenv("GEMMA_MODEL", "other-provider-model")
    with pytest.raises(ValueError, match="not a permitted Gemma 4 model"):
        get_configured_gemma_model()

    monkeypatch.setenv("GEMMA_MODEL", "gpt-4o")
    with pytest.raises(ValueError, match="not a permitted Gemma 4 model"):
        get_configured_gemma_model()



def test_parse_gemma_response_valid():
    raw_json = json.dumps(SAMPLE_VALID_ANALYSIS)
    parsed = parse_gemma_response(raw_json)
    assert parsed["confidence"] == "high"
    assert "discounts.py" in parsed["supporting_evidence"][0]["file"]


def test_parse_gemma_response_fenced():
    raw_fenced = f"```json\n{json.dumps(SAMPLE_VALID_ANALYSIS)}\n```"
    parsed = parse_gemma_response(raw_fenced)
    assert parsed["likely_root_cause"] == SAMPLE_VALID_ANALYSIS["likely_root_cause"]

    # Also test generic code fences without 'json' tag
    raw_generic_fenced = f"```\n{json.dumps(SAMPLE_VALID_ANALYSIS)}\n```"
    parsed_generic = parse_gemma_response(raw_generic_fenced)
    assert parsed_generic["confidence"] == "high"


def test_parse_gemma_response_malformed():
    with pytest.raises(ValueError, match="not valid JSON"):
        parse_gemma_response("This is not JSON at all.")

    with pytest.raises(ValueError, match="must be a JSON object"):
        parse_gemma_response("[1, 2, 3]")

    # Missing required key
    incomplete = dict(SAMPLE_VALID_ANALYSIS)
    del incomplete["likely_root_cause"]
    with pytest.raises(ValueError, match="missing required fields"):
        parse_gemma_response(json.dumps(incomplete))


def test_call_gemma_empty_issue(tmp_path: Path):
    res = call_gemma_analysis(tmp_path, issue_text="")
    assert res["status"] == "invalid_input"
    assert "cannot be empty" in res["error"]

    res_spaces = call_gemma_analysis(tmp_path, issue_text="   ")
    assert res_spaces["status"] == "invalid_input"


def test_call_gemma_invalid_image(tmp_path: Path):
    root = tmp_path.resolve()

    # Image does not exist
    res_missing = call_gemma_analysis(root, issue_text="bug report", screenshot_path="missing.png")
    assert res_missing["status"] == "invalid_image"
    assert "does not exist" in res_missing["error"]

    # Image outside workspace
    outside = (tmp_path.parent / "outside.png").resolve()
    outside.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    try:
        res_outside = call_gemma_analysis(root, issue_text="bug report", screenshot_path=str(outside))
        assert res_outside["status"] == "invalid_image"
        assert "inside the configured" in res_outside["error"]
    finally:
        if outside.exists():
            outside.unlink()

    # Invalid image signature
    fake = root / "fake.png"
    fake.write_bytes(b"not an image")
    res_fake = call_gemma_analysis(root, issue_text="bug report", screenshot_path="fake.png")
    assert res_fake["status"] == "invalid_image"
    assert "signature" in res_fake["error"]


def test_call_gemma_missing_api_key(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    res = call_gemma_analysis(tmp_path, issue_text="Discount gives 120 instead of 80")
    assert res["status"] == "not_configured"
    assert "GEMINI_API_KEY is not set" in res["error"]
    assert "privacy_notice" in res


def test_call_gemma_mocked_success(tmp_path: Path, monkeypatch):
    root = tmp_path.resolve()
    img_dir = root / "evidence"
    img_dir.mkdir()
    valid_png = img_dir / "bug.png"
    valid_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)

    monkeypatch.setenv("GEMINI_API_KEY", "mock-test-key-12345")

    # Set up mock Google GenAI client
    mock_client = MagicMock()
    mock_uploaded_file = MagicMock()
    mock_uploaded_file.name = "files/test-upload-id"
    mock_client.files.upload.return_value = mock_uploaded_file

    mock_response = MagicMock()
    mock_response.text = f"```json\n{json.dumps(SAMPLE_VALID_ANALYSIS)}\n```"
    mock_client.models.generate_content.return_value = mock_response

    repo_evidence = [{"file": "discounts.py", "line": 3, "text": "def calculate_discount"}]
    test_evidence = "FAILED test_discounts.py - assert 120.0 == 80.0"

    res = call_gemma_analysis(
        root=root,
        issue_text="Discount total shows 120 instead of 80",
        screenshot_path="evidence/bug.png",
        repository_evidence=repo_evidence,
        test_evidence=test_evidence,
        client=mock_client,
    )

    assert res["status"] == "success"
    assert res["model"] == DEFAULT_GEMMA_MODEL
    assert res["has_screenshot"] is True
    assert res["analysis"]["likely_root_cause"] == SAMPLE_VALID_ANALYSIS["likely_root_cause"]

    # Verify screenshot was uploaded and contents passed to model
    mock_client.files.upload.assert_called_once_with(file=str(valid_png.resolve()))
    call_args = mock_client.models.generate_content.call_args[1]
    assert call_args["model"] == DEFAULT_GEMMA_MODEL
    assert mock_uploaded_file in call_args["contents"]

    # Verify uploaded file cleanup
    mock_client.files.delete.assert_called_once_with(name="files/test-upload-id")


def test_call_gemma_api_exception_redacts_key(tmp_path: Path, monkeypatch):
    root = tmp_path.resolve()
    fake_secret_key = "MY_ULTRA_SECRET_API_KEY_xyz987"
    monkeypatch.setenv("GEMINI_API_KEY", fake_secret_key)

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = RuntimeError(
        f"API failed for request authenticated with key {fake_secret_key}: quota exceeded"
    )

    res = call_gemma_analysis(
        root=root,
        issue_text="Discount bug report",
        client=mock_client,
    )

    assert res["status"] == "api_error"
    # Ensure raw secret key is NOT leaked in the response error message
    assert fake_secret_key not in res["error"]
    assert "[REDACTED_API_KEY]" in res["error"]
