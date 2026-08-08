"""Alerting webhook delivery for ScriptRunner.

Delivery is best-effort: any HTTP error from the webhook must not propagate into
the run or the retry state. The webhook fires only once per retry cycle, on the
final failure after `retry_max` retries are exhausted.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)


class WebhookError(ValueError):
    """Raised when the webhook URL is malformed or unusable."""


def validate_webhook_url(url: str) -> str:
    """Verify the URL has a scheme that `requests` can POST to."""
    if not url or not url.strip():
        raise WebhookError("webhook url must not be empty")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise WebhookError(f"webhook url must use http or https (got {parsed.scheme!r})")
    if not parsed.netloc:
        raise WebhookError("webhook url must include a host")
    return url


def build_alert_payload(
    *,
    schedule_id: int,
    script_id: int,
    run_id: int,
    status: str,
    exit_code: int | None,
    log_path: str | None,
    retry_attempt: int,
) -> dict[str, Any]:
    """Return the JSON body that gets POSTed to the alerting webhook."""
    return {
        "schedule_id": schedule_id,
        "script_id": script_id,
        "run_id": run_id,
        "status": status,
        "exit_code": exit_code,
        "log_path": log_path,
        "retry_attempt": retry_attempt,
    }


def post_alert(
    url: str,
    payload: dict[str, Any],
    *,
    timeout: float = 5.0,
    session: requests.Session | None = None,
) -> bool:
    """POST `payload` to `url`. Returns True on a 2xx, False on any error.

    Best-effort: any exception (timeout, connection error, non-2xx) is logged
    and swallowed. The caller should treat a False return as "delivery failed"
    but never raise.
    """
    try:
        validate_webhook_url(url)
    except WebhookError as exc:
        logger.warning("refusing to POST alert to invalid webhook url: %s", exc)
        return False

    sender = session or requests
    try:
        response = sender.post(url, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        logger.warning("alerting webhook POST failed: %s", exc)
        return False

    if not 200 <= response.status_code < 300:
        logger.warning(
            "alerting webhook returned non-2xx status %s for url %s",
            response.status_code,
            url,
        )
        return False
    return True
