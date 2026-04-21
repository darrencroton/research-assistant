"""Shared retry helpers for transient LLM failures."""

from __future__ import annotations


_NON_RETRYABLE_LLM_ERROR_MARKERS = (
    "credit balance is too low",
    "api key",
    "authentication",
    "logged out",
    "login required",
    "not logged in",
    "not authenticated",
    "no authentication information found",
    "not found on path",
)


def is_retryable_llm_error(error: Exception) -> bool:
    """Return True when an LLM failure looks transient and worth retrying."""
    message = str(error).lower()
    return not any(marker in message for marker in _NON_RETRYABLE_LLM_ERROR_MARKERS)
