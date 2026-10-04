"""Thin async clients for Ollama and OpenAI-compatible chat APIs (plain httpx, no SDKs)."""
import base64
from typing import Optional

import httpx

from .config import settings


class LLMError(Exception):
    """A problem talking to the language model, with a message safe to show the user."""


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(settings.request_timeout, connect=15.0))


# ----------------------------------------------------------------------------------
# Ollama
# ----------------------------------------------------------------------------------
async def _ollama_chat(model: str, system: str, user: str, image_b64: Optional[str] = None) -> str:
    user_msg: dict = {"role": "user", "content": user}
    if image_b64:
        user_msg["images"] = [image_b64]
    payload = {
        "model": model,
        "stream": False,
        "messages": [{"role": "system", "content": system}, user_msg],
        "options": {"temperature": settings.temperature, "num_ctx": settings.ollama_num_ctx},
    }
    try:
        async with _client() as client:
            resp = await client.post(f"{settings.ollama_host}/api/chat", json=payload)
    except httpx.ConnectError:
        raise LLMError(
            f"Cannot reach Ollama at {settings.ollama_host}. Make sure `ollama serve` is running."
        )
    except httpx.TimeoutException:
        raise LLMError("The model took too long to respond. Try again, or use a smaller input.")

    if resp.status_code == 404:
        raise LLMError(f"Model '{model}' is not installed. Run: ollama pull {model}")
    if resp.status_code >= 400:
        raise LLMError(f"Ollama error {resp.status_code}: {resp.text[:300]}")
    try:
        return (resp.json()["message"]["content"] or "").strip()
    except (KeyError, ValueError):
        raise LLMError("Ollama returned an unexpected response.")


# ----------------------------------------------------------------------------------
# OpenAI-compatible
# ----------------------------------------------------------------------------------
async def _openai_chat(
    model: str, system: str, user: str, image_b64: Optional[str] = None, mime: str = "image/png"
) -> str:
    if not settings.openai_api_key:
        raise LLMError("OPENAI_API_KEY is not set on the server.")
    if image_b64:
        user_content = [
            {"type": "text", "text": user},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
        ]
    else:
        user_content = user
    payload = {
        "model": model,
        "temperature": settings.temperature,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_content}],
    }
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    try:
        async with _client() as client:
            resp = await client.post(f"{settings.openai_base_url}/chat/completions", json=payload, headers=headers)
    except httpx.ConnectError:
        raise LLMError(f"Cannot reach {settings.openai_base_url}.")
    except httpx.TimeoutException:
        raise LLMError("The model took too long to respond. Try again, or use a smaller input.")

    if resp.status_code in (401, 403):
        raise LLMError("The model API rejected the API key.")
    if resp.status_code == 429:
        raise LLMError("The model API rate limit was hit. Wait a moment and try again.")
    if resp.status_code >= 400:
        raise LLMError(f"Model API error {resp.status_code}: {resp.text[:300]}")
    try:
        return (resp.json()["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, ValueError):
        raise LLMError("The model API returned an unexpected response.")


# ----------------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------------
async def generate(system: str, user: str) -> str:
    """Run one text generation call."""
    if settings.provider == "ollama":
        return await _ollama_chat(settings.text_model, system, user)
    return await _openai_chat(settings.text_model, system, user)


async def describe_image(data: bytes, mime: str, instruction: str) -> str:
    """Send an image to the vision model and return its text answer."""
    b64 = base64.b64encode(data).decode("ascii")
    system = "You are a precise OCR and image-reading assistant."
    if settings.provider == "ollama":
        return await _ollama_chat(settings.vision_model, system, instruction, image_b64=b64)
    return await _openai_chat(settings.vision_model, system, instruction, image_b64=b64, mime=mime)


async def health() -> dict:
    """Report whether the configured model backend is reachable."""
    info = {"provider": settings.provider, "model": settings.text_model, "vision_model": settings.vision_model}
    if settings.provider == "ollama":
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{settings.ollama_host}/api/tags")
            resp.raise_for_status()
            installed = {m.get("name", "") for m in resp.json().get("models", [])}

            def has(name: str) -> bool:
                return name in installed or (":" not in name and f"{name}:latest" in installed)

            info.update(
                reachable=True,
                text_model_installed=has(settings.text_model),
                vision_model_installed=has(settings.vision_model),
            )
        except Exception:
            info.update(reachable=False)
    else:
        info.update(reachable=bool(settings.openai_api_key), api_key_set=bool(settings.openai_api_key))
    return info
