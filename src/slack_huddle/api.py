"""Slack web-client API wrapper for huddle transcripts.

The three-step pipeline:
1. ``huddles.history`` lists huddles in a channel (or workspace-wide).
   Each huddle's ``transcript_file_id`` field is actually the AI-summary CANVAS file ID
   (Slack's naming is counterintuitive).
2. ``files.info`` on the canvas returns its ``huddle_transcript_file_id``, which is
   the raw transcript file (mimetype ``application/vnd.slack-huddle-transcript``).
3. ``files.info`` on the raw transcript file with ``include_transcription=true``
   returns the populated ``huddle_transcription`` payload.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
DEFAULT_USER_AGENT = "slack-huddle-mcp/0.3.0 (+https://github.com/prithvi-bharadwaj/slack-huddle-mcp)"
MAX_RETRIES = 3


class SlackApiError(RuntimeError):
    """Raised when Slack returns ``ok: false``."""

    def __init__(self, error: str, response: dict[str, Any] | None = None) -> None:
        super().__init__(error)
        self.error = error
        self.response = response or {}


class AuthError(SlackApiError):
    """Raised on 401/403 or auth-related Slack errors. Halts; never retried."""


class RateLimitError(SlackApiError):
    """Raised when Slack returns 429 and retries are exhausted."""

    def __init__(self, retry_after: float) -> None:
        super().__init__(f"rate_limited (retry_after={retry_after:.1f}s)")
        self.retry_after = retry_after


_AUTH_ERROR_CODES = {
    "invalid_auth",
    "not_authed",
    "token_revoked",
    "account_inactive",
    "no_permission",
    "missing_scope",
    "team_added_to_org",
}


class SlackHuddleClient:
    """Synchronous Slack web-client API wrapper.

    Both ``xoxc`` (form ``token``) and ``xoxd`` (Cookie ``d=``) are required.
    Tokens never appear in logs.
    """

    def __init__(
        self,
        xoxc_token: str,
        xoxd_cookie: str,
        workspace_subdomain: str,
        *,
        http_client: httpx.Client | None = None,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        if not xoxc_token.startswith("xoxc-"):
            raise ValueError("xoxc_token must start with 'xoxc-'")
        if not xoxd_cookie:
            raise ValueError("xoxd_cookie is required")
        if not workspace_subdomain:
            raise ValueError("workspace_subdomain is required")

        self._xoxc = xoxc_token
        self._xoxd = xoxd_cookie
        self.workspace_subdomain = workspace_subdomain
        self._base_url = f"https://{workspace_subdomain}.slack.com/api"
        self._max_retries = max_retries
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(timeout=timeout)

    def __enter__(self) -> SlackHuddleClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _request(self, method: str, **fields: Any) -> dict[str, Any]:
        url = f"{self._base_url}/{method}"
        form: dict[str, str] = {"token": self._xoxc}
        for key, value in fields.items():
            if value is None:
                continue
            form[key] = "true" if value is True else "false" if value is False else str(value)

        headers = {
            "Cookie": f"d={self._xoxd}",
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "application/json",
        }
        files: dict[str, tuple[None, str]] = {k: (None, v) for k, v in form.items()}

        attempt = 0
        while True:
            attempt += 1
            try:
                response = self._client.post(url, headers=headers, files=files)
            except httpx.HTTPError as exc:
                if attempt >= self._max_retries:
                    raise SlackApiError(f"network_error: {exc!s}") from exc
                _sleep_backoff(attempt)
                continue

            if response.status_code in (401, 403):
                raise AuthError(
                    f"http_{response.status_code}_unauthorized",
                    {"status_code": response.status_code},
                )
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", "1"))
                if attempt >= self._max_retries:
                    raise RateLimitError(retry_after)
                logger.debug("rate-limited on %s, retrying after %.1fs", method, retry_after)
                time.sleep(retry_after)
                continue
            if response.status_code >= 500:
                if attempt >= self._max_retries:
                    raise SlackApiError(f"http_{response.status_code}_server_error")
                _sleep_backoff(attempt)
                continue

            try:
                data: dict[str, Any] = response.json()
            except ValueError as exc:
                raise SlackApiError(f"invalid_json_from_{method}") from exc

            if not data.get("ok", False):
                error_code = str(data.get("error", "unknown_error"))
                if error_code in _AUTH_ERROR_CODES:
                    raise AuthError(error_code, data)
                if error_code == "ratelimited":
                    retry_after = float(data.get("retry_after", 1))
                    if attempt >= self._max_retries:
                        raise RateLimitError(retry_after)
                    time.sleep(retry_after)
                    continue
                raise SlackApiError(error_code, data)

            return data

    def auth_test(self) -> dict[str, Any]:
        """Verify tokens and return user/team info."""
        return self._request("auth.test")

    def huddles_history(
        self,
        *,
        channel_id: str | None = None,
        limit: int = 50,
        oldest: float | None = None,
        latest: float | None = None,
    ) -> list[dict[str, Any]]:
        """List huddles, optionally scoped to a channel.

        Returns the raw ``huddles`` list from Slack. Each entry contains
        ``id``, ``date_start``, ``date_end``, ``channels``, ``participant_history``,
        ``transcript_file_id`` (the AI-summary CANVAS file id), ``huddle_link``,
        ``thread_root_ts``.
        """
        data = self._request(
            "huddles.history",
            channel=channel_id,
            limit=limit,
            oldest=oldest,
            latest=latest,
        )
        huddles = data.get("huddles", [])
        if not isinstance(huddles, list):
            return []
        return [h for h in huddles if isinstance(h, dict)]

    def files_info(
        self,
        file_id: str,
        *,
        include_transcription: bool = False,
        page: int = 1,
        count: int = 500,
        truncate: bool = True,
    ) -> dict[str, Any]:
        """Fetch a file. Pass ``include_transcription=True`` for huddle transcript files."""
        data = self._request(
            "files.info",
            file=file_id,
            include_transcription=include_transcription,
            page=page,
            count=count,
            truncate=truncate,
        )
        file_obj = data.get("file")
        if not isinstance(file_obj, dict):
            raise SlackApiError("missing_file_in_response", data)
        return file_obj

    def resolve_transcript_file_id(self, canvas_id: str) -> str:
        """Given a huddle's canvas file ID, return the raw transcript file ID."""
        canvas = self.files_info(canvas_id)
        transcript_file_id = canvas.get("huddle_transcript_file_id")
        if not isinstance(transcript_file_id, str) or not transcript_file_id:
            raise SlackApiError(
                "missing_huddle_transcript_file_id",
                {"canvas_id": canvas_id, "is_huddle_canvas": canvas.get("is_huddle_canvas")},
            )
        return transcript_file_id

    def fetch_transcription(self, transcript_file_id: str) -> dict[str, Any]:
        """Fetch and return the ``huddle_transcription`` payload for a transcript file."""
        file_obj = self.files_info(transcript_file_id, include_transcription=True)
        transcription = file_obj.get("huddle_transcription")
        if not isinstance(transcription, dict):
            raise SlackApiError(
                "missing_huddle_transcription",
                {"file_id": transcript_file_id},
            )
        return transcription

    def fetch_huddle_summary_canvas(self, canvas_id: str) -> dict[str, Any]:
        """Fetch the AI-summary canvas file directly. Returns the canvas file dict."""
        canvas = self.files_info(canvas_id)
        if not canvas.get("is_huddle_canvas"):
            raise SlackApiError(
                "not_a_huddle_canvas",
                {"canvas_id": canvas_id, "mimetype": canvas.get("mimetype")},
            )
        return canvas


def _sleep_backoff(attempt: int) -> None:
    """Exponential backoff capped at 8 seconds."""
    delay = min(2.0 ** (attempt - 1), 8.0)
    time.sleep(delay)
