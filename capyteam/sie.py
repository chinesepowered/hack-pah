"""Superlinked SIE Serverless: every model call CapyTeam makes.

No frontier model anywhere. Each step uses a task-specific open model:
  chat + tool calling   Qwen/Qwen3.8-27B-FP8          (/v1/chat/completions)
  intent routing        GLiClass instruct large       (/v1/extract)
  injection screening   GLiClass instruct large       (/v1/extract, safety labels)
  field extraction      GLiNER2 large                 (/v1/extract with output_schema)
  lesson recall         Qwen3-Embedding-4B (2560-d)   (/v1/encode)
  lesson ranking        Qwen3-Reranker-4B             (/v1/score)
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx
from openai import AsyncOpenAI

from .config import settings

# SIE reports billed credits on every response. Dollar conversion is an assumption you can override.
CREDIT_USD = float(os.environ.get("SIE_CREDIT_USD", "0.0001"))


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    credits: float = 0.0
    latency_ms: float = 0.0
    by_model: dict[str, dict[str, float]] = field(default_factory=dict)

    def add(self, model: str, input_tokens: int = 0, output_tokens: int = 0, credits: float = 0.0, latency_ms: float = 0.0) -> None:
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.credits += credits
        self.latency_ms += latency_ms
        m = self.by_model.setdefault(model, {"calls": 0, "credits": 0.0, "tokens": 0})
        m["calls"] += 1
        m["credits"] += credits
        m["tokens"] += input_tokens + output_tokens

    @property
    def cost_usd(self) -> float:
        return round(self.credits * CREDIT_USD, 6)


class SIE:
    def __init__(self) -> None:
        self._oa: AsyncOpenAI | None = None
        self._http: httpx.AsyncClient | None = None
        self._gen_sem = asyncio.Semaphore(max(1, settings.sie_generation_concurrency))
        self._rt_sem = asyncio.Semaphore(24)

    # ---------------- clients ----------------
    def oa(self) -> AsyncOpenAI:
        if self._oa is None:
            self._oa = AsyncOpenAI(
                base_url=f"{settings.sie_base_url}/v1", api_key=settings.sie_api_key, max_retries=6,
                timeout=httpx.Timeout(120.0, connect=20.0),
            )
        return self._oa

    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=settings.sie_base_url,
                headers={"Authorization": f"Bearer {settings.sie_api_key}", "Accept": "application/json"},
                timeout=httpx.Timeout(120.0, connect=20.0),
                limits=httpx.Limits(max_connections=48, max_keepalive_connections=24),
            )
        return self._http

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None

    # ---------------- generation ----------------
    async def chat(self, messages: list[dict], tools: list[dict] | None = None, *, model: str | None = None,
                   max_tokens: int = 700, temperature: float = 0.0, usage: Usage | None = None,
                   response_format: dict | None = None) -> Any:
        model = model or settings.model_agent
        kwargs: dict[str, Any] = dict(model=model, messages=messages, max_tokens=max_tokens, temperature=temperature)
        if tools:
            kwargs["tools"] = tools
        if response_format:
            kwargs["response_format"] = response_format
        async with self._gen_sem:
            t = time.perf_counter()
            resp = await self.oa().chat.completions.create(**kwargs)
            dt = (time.perf_counter() - t) * 1000
        u = resp.usage
        credits = float(getattr(u, "credits_charged_decimal", None) or getattr(u, "credits_charged", 0) or 0) if u else 0.0
        if usage is not None:
            usage.add(model, getattr(u, "prompt_tokens", 0) or 0, getattr(u, "completion_tokens", 0) or 0, credits, dt)
        resp._capy_latency_ms = dt  # type: ignore[attr-defined]
        resp._capy_credits = credits  # type: ignore[attr-defined]
        return resp

    # ---------------- realtime primitives ----------------
    async def _post(self, path: str, body: dict, model: str, usage: Usage | None, provision_timeout: float = 480.0) -> dict:
        last: Exception | None = None
        deadline = time.monotonic() + provision_timeout
        attempt = -1
        while time.monotonic() < deadline:
            attempt += 1
            async with self._rt_sem:
                t = time.perf_counter()
                try:
                    r = await self.http().post(path, json=body)
                except httpx.TransportError as e:
                    last = e
                    await asyncio.sleep(min(8, 0.5 * 2**attempt))
                    continue
                dt = (time.perf_counter() - t) * 1000
            if r.status_code in (429, 502, 503, 504):
                wait = float(r.headers.get("retry-after", "2") or 2)
                last = RuntimeError(f"{r.status_code} {r.text[:120]}")
                await asyncio.sleep(min(wait, 20))
                continue
            r.raise_for_status()
            data = r.json()
            u = data.get("usage") or {}
            if usage is not None:
                usage.add(model, int(u.get("input_tokens", 0) or 0), 0,
                          float(u.get("credits_charged_decimal") or u.get("credits_charged") or 0), dt)
            return data
        raise RuntimeError(f"SIE {path} failed after retries: {last}")

    async def classify(self, text: str, labels: list[str], *, usage: Usage | None = None, model: str | None = None) -> list[tuple[str, float]]:
        model = model or settings.model_classify
        data = await self._post(f"/v1/extract/{quote(model, safe='')}", {"items": [{"text": text[:1800]}], "params": {"labels": labels, "options": {"overflow_policy": "truncate_text"}}}, model, usage)
        cls = (data.get("items") or [{}])[0].get("classifications") or []
        return [(c["label"], float(c["score"])) for c in cls]

    async def extract(self, text: str, schema: dict, *, usage: Usage | None = None, model: str | None = None) -> dict:
        model = model or settings.model_extract
        data = await self._post(f"/v1/extract/{quote(model, safe='')}", {"items": [{"text": text[:4000]}], "params": {"output_schema": schema}}, model, usage)
        return (data.get("items") or [{}])[0].get("data") or {}

    async def entities(self, text: str, labels: list[str], *, usage: Usage | None = None, model: str | None = None) -> list[dict]:
        model = model or settings.model_extract
        data = await self._post(f"/v1/extract/{quote(model, safe='')}", {"items": [{"text": text[:4000]}], "params": {"labels": labels}}, model, usage)
        return (data.get("items") or [{}])[0].get("entities") or []

    async def embed(self, texts: list[str], *, is_query: bool = False, usage: Usage | None = None, model: str | None = None) -> list[list[float]]:
        model = model or settings.model_embed
        params: dict[str, Any] = {"output_types": ["dense"]}
        if is_query:
            params["options"] = {"is_query": True}
        data = await self._post(f"/v1/encode/{quote(model, safe='')}", {"items": [{"text": t[:6000]} for t in texts], "params": params}, model, usage)
        out = []
        for it in data.get("items", []):
            d = it.get("dense") or {}
            out.append(d.get("values") if isinstance(d, dict) else d)
        return out

    async def rerank(self, query: str, docs: list[tuple[str, str]], *, usage: Usage | None = None, model: str | None = None) -> list[tuple[str, float]]:
        if not docs:
            return []
        model = model or settings.model_rerank
        data = await self._post(f"/v1/score/{quote(model, safe='')}", {"query": {"text": query[:2000]}, "items": [{"id": i, "text": t[:2000]} for i, t in docs]}, model, usage)
        return [(s["item_id"], float(s["score"])) for s in data.get("scores", [])]

    async def warmup(self) -> dict:
        """Wake every task model (SIE Serverless scales idle models to zero) before a big run."""
        t = time.perf_counter()
        await asyncio.gather(
            self.embed(["warm up"]), self.rerank("warm up", [("a", "warm up")]),
            self.classify("warm up", ["a", "b"]), self.extract("Jess paid $38", {"type": "object", "properties": {"amount": {"type": "string"}}}),
            self.chat([{"role": "user", "content": "Reply with OK."}], max_tokens=4),
        )
        return {"warm_seconds": round(time.perf_counter() - t, 1)}

    async def screen(self, text: str, *, usage: Usage | None = None) -> dict:
        """Prompt-injection / fraud screen for inbound text (emails, chat)."""
        labels = [
            "asks to ignore or override instructions",
            "asks to send money to a new or different account",
            "normal business request",
        ]
        scores = dict(await self.classify(text, labels, usage=usage, model=settings.model_guard))
        risk = max(scores.get(labels[0], 0.0), scores.get(labels[1], 0.0))
        return {"risky": risk >= 0.6, "risk": round(risk, 3), "scores": scores}


sie = SIE()
