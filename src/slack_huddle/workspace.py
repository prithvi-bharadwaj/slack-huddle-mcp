"""Workspace subdomain resolution via Slack's ``auth.test`` endpoint."""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from slack_huddle.api import AuthError, SlackApiError

_SUBDOMAIN_RE = re.compile(r"https?://([a-z0-9-]+)\.slack\.com/?", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class WorkspaceInfo:
    """Identifies a Slack workspace."""

    subdomain: str
    team_id: str
    team_name: str
    user_id: str


def resolve_workspace(
    xoxc: str,
    xoxd: str,
    *,
    hint: str | None = None,
    http_client: httpx.Client | None = None,
) -> WorkspaceInfo:
    """Resolve a workspace's subdomain by calling ``auth.test`` against ``hint``
    (or ``slack.com`` if no hint).

    A ``hint`` short-circuits the lookup when known. Without a hint the function
    falls back to the bare ``slack.com`` host, which Slack also accepts for
    ``auth.test`` calls.
    """
    if hint:
        hint = hint.strip().lower().removesuffix(".slack.com")

    candidate_hosts = [hint] if hint else ["slack.com"]
    last_error: Exception | None = None
    owns_client = http_client is None
    client = http_client or httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0))

    try:
        for host in candidate_hosts:
            base = host if host == "slack.com" else f"{host}.slack.com"
            url = f"https://{base}/api/auth.test"
            try:
                response = client.post(
                    url,
                    headers={
                        "Cookie": f"d={xoxd}",
                        "Accept": "application/json",
                    },
                    files={"token": (None, xoxc)},
                )
            except httpx.HTTPError as exc:
                last_error = exc
                continue

            if response.status_code in (401, 403):
                raise AuthError(f"http_{response.status_code}_unauthorized")
            if response.status_code >= 400:
                last_error = SlackApiError(f"http_{response.status_code}")
                continue

            data = response.json()
            if not data.get("ok"):
                error_code = str(data.get("error", "unknown"))
                if error_code in {"invalid_auth", "not_authed", "token_revoked"}:
                    raise AuthError(error_code, data)
                last_error = SlackApiError(error_code, data)
                continue

            subdomain = _subdomain_from_url(data.get("url"))
            if not subdomain and hint:
                subdomain = hint
            if not subdomain:
                raise SlackApiError("could_not_resolve_subdomain", data)

            return WorkspaceInfo(
                subdomain=subdomain,
                team_id=str(data.get("team_id", "")),
                team_name=str(data.get("team", "")),
                user_id=str(data.get("user_id", "")),
            )
    finally:
        if owns_client:
            client.close()

    if last_error is None:
        raise SlackApiError("workspace_resolution_failed")
    if isinstance(last_error, (AuthError, SlackApiError)):
        raise last_error
    raise SlackApiError("workspace_resolution_failed") from last_error


def _subdomain_from_url(url: object) -> str | None:
    if not isinstance(url, str):
        return None
    match = _SUBDOMAIN_RE.match(url)
    if not match:
        return None
    return match.group(1).lower()
