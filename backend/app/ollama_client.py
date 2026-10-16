"""Local Ollama client. Never calls any cloud API."""
from __future__ import annotations
import json
from typing import AsyncIterator, Optional

import httpx

from . import config

TIMEOUT = httpx.Timeout(180.0, connect=10.0)


def base() -> str:
    return config.OLLAMA_HOST.rstrip("/")


async def is_available() -> bool:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as c:
            r = await c.get(base() + "/api/tags")
            return r.status_code == 200
    except Exception:
        return False


async def list_models() -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as c:
            r = await c.get(base() + "/api/tags")
            r.raise_for_status()
            data = r.json()
            return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return []


async def has_model(name: str) -> bool:
    models = await list_models()
    # exact or prefix match (ollama tags like qwen3.5:9b)
    return any(m == name or m.startswith(name + ":") or name == m for m in models)


async def embed(texts: list[str], model: Optional[str] = None) -> list[list[float]]:
    """Call local /api/embed. Batches to avoid RAM spikes."""
    model = model or config.EMBED_MODEL
    out: list[list[float]] = []
    batch = 8
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        for i in range(0, len(texts), batch):
            part = texts[i : i + batch]
            # Ollama /api/embed accepts {model, input}
            r = await c.post(base() + "/api/embed", json={"model": model, "input": part})
            if r.status_code == 404:
                # older Ollama: /api/embeddings one-by-one
                for t in part:
                    r2 = await c.post(base() + "/api/embeddings", json={"model": model, "prompt": t})
                    r2.raise_for_status()
                    out.append(r2.json()["embedding"])
                continue
            r.raise_for_status()
            data = r.json()
            embs = data.get("embeddings") or []
            out.extend(embs)
    return out


def _think_payload() -> dict:
    # qwen3.5 is a thinking model: its chain-of-thought can consume the whole
    # token budget leaving empty answers on CPU. Disable thinking by default
    # for fast grounded RAG; set STUDY_ENABLE_THINK=1 to re-enable.
    import os as _os
    if _os.environ.get("STUDY_ENABLE_THINK", "0") == "1":
        return {}
    return {"think": False}


async def chat(messages: list[dict], model: Optional[str] = None, stream: bool = False, num_ctx: Optional[int] = None, max_tokens: Optional[int] = None, temperature: Optional[float] = None):
    """Non-streaming chat via /api/chat."""
    model = model or config.CHAT_MODEL
    opts = {
        "num_ctx": num_ctx or config.OLLAMA_NUM_CTX,
        "num_predict": max_tokens or config.GEN_MAX_TOKENS,
        "temperature": config.GEN_TEMPERATURE if temperature is None else temperature,
    }
    payload = {"model": model, "messages": messages, "stream": False, "options": opts, **_think_payload()}
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(base() + "/api/chat", json=payload)
        r.raise_for_status()
        data = r.json()
        msg = data.get("message", {})
        content = msg.get("content", "") or ""
        if not content.strip() and msg.get("thinking"):
            # thinking model spent budget on reasoning; retry without thinking
            payload["think"] = False
            r2 = await c.post(base() + "/api/chat", json=payload)
            r2.raise_for_status()
            content = r2.json().get("message", {}).get("content", "") or ""
        return content


async def chat_stream(messages: list[dict], model: Optional[str] = None, num_ctx: Optional[int] = None, max_tokens: Optional[int] = None, temperature: Optional[float] = None) -> AsyncIterator[str]:
    model = model or config.CHAT_MODEL
    opts = {
        "num_ctx": num_ctx or config.OLLAMA_NUM_CTX,
        "num_predict": max_tokens or config.GEN_MAX_TOKENS,
        "temperature": config.GEN_TEMPERATURE if temperature is None else temperature,
    }
    payload = {"model": model, "messages": messages, "stream": True, "options": opts, **_think_payload()}
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        async with c.stream("POST", base() + "/api/chat", json=payload) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("error"):
                    yield "\n[Ollama error: " + str(obj["error"]) + "]"
                    break
                msg = obj.get("message", {})
                delta = msg.get("content", "")
                if delta:
                    yield delta
                if obj.get("done"):
                    break
