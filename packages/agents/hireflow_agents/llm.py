from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class LLMError(Exception):
    """Raised when the model gateway cannot return valid structured output."""


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float = 60
    max_retries: int = 1
    temperature: float = 0
    json_mode: bool = True
    max_output_tokens: int = 4096


def _extract_json(text: str) -> str:
    text = text.strip()
    fenced = _FENCE.search(text)
    if fenced:
        return fenced.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


async def complete_json(
    config: LLMConfig,
    *,
    system: str,
    user: str,
    schema: type[T],
    agent: str,
) -> T:
    if not config.api_key:
        raise LLMError("LLM is not configured")

    schema_hint = json.dumps(schema.model_json_schema(), indent=2)
    base_user = (
        f"{user}\n\nReturn ONLY valid JSON matching this schema:\n{schema_hint}"
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": base_user},
    ]

    last_error = "invalid JSON"
    for attempt in range(config.max_retries + 1):
        raw = await _chat(config, messages, use_json_mode=config.json_mode)
        try:
            payload = json.loads(_extract_json(raw))
            return schema.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = str(exc)
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Your previous output was invalid ({last_error}). "
                        "Reply again with ONLY corrected JSON. No markdown."
                    ),
                }
            )
    raise LLMError(f"{agent} returned invalid JSON: {last_error}")


async def _chat(config: LLMConfig, messages: list[dict[str, str]], *, use_json_mode: bool) -> str:
    url = config.base_url.rstrip("/") + "/chat/completions"
    body: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
        "max_tokens": config.max_output_tokens,
    }
    if use_json_mode:
        body["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
        response: httpx.Response | None = None
        attempts = max(1, config.max_retries + 1)
        for attempt in range(attempts):
            response = await client.post(url, headers=headers, json=body)
            if response.status_code >= 400 and use_json_mode:
                body.pop("response_format", None)
                response = await client.post(url, headers=headers, json=body)
            if response.status_code == 429 and attempt + 1 < attempts:
                retry_after = response.headers.get("retry-after")
                try:
                    wait_s = min(max(float(retry_after), 1.0), 20.0) if retry_after else 3.0
                except ValueError:
                    wait_s = 3.0
                await asyncio.sleep(wait_s)
                continue
            break

        assert response is not None
        if response.status_code >= 400:
            detail = response.text.strip().replace("\n", " ")[:240]
            if response.status_code == 429:
                raise LLMError(
                    "Groq rate limit reached. Wait about a minute, then click Retry on this page."
                )
            if response.status_code == 413:
                raise LLMError(
                    "The resume or match request is too large for the AI model. "
                    "Retry screening — if it persists, use a shorter resume or fewer JD requirements."
                )
            raise LLMError(
                f"LLM request failed ({response.status_code})"
                + (f": {detail}" if detail else "")
            )
        data = response.json()

    try:
        message = data["choices"][0]["message"]
        content = message.get("content") or ""
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part) for part in content
            )
        if not content:
            content = message.get("reasoning") or ""
        return str(content)
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError("LLM response missing content") from exc
