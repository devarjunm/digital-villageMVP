"""LLM provider abstraction.

Why an abstraction: the platform must run, and be testable, without any external
AI service — and it must never pretend a language model answered when one did not.

Supported providers (LLM_PROVIDER):
  * `mock`      — offline, deterministic, extractive (default in development);
  * `openai`    — OpenAI /chat/completions;
  * `custom`    — any OpenAI-compatible gateway (LLM_BASE_URL);
  * `ollama`    — self-hosted models (e.g. a district-level edge box);
  * `anthropic` — Claude messages API.

Grounding contract enforced by the caller (genai.rag.pipeline):
  * the retrieval pipeline only calls the provider when evidence passed the score
    floor, and it puts the evidence in a `CONTEXT:` system message;
  * `MockLLMProvider` refuses to answer without that context, so the demo path
    cannot invent agricultural facts either;
  * every response reports `provider`, `model` and `is_demo`, and the API surfaces
    those fields so a user can always tell what answered.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.config import settings
from app.core.errors import ConfigurationError
from app.core.logging import get_logger
from app.core.observability import LLM_TOKEN_COUNTER

logger = get_logger(__name__)


@dataclass(slots=True)
class LLMMessage:
    role: str  # system | user | assistant
    content: str


@dataclass(slots=True)
class LLMResult:
    text: str
    provider: str
    model: str
    is_demo: bool
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None
    notices: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class LLMProvider(Protocol):
    name: str
    model: str
    is_demo: bool

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResult: ...

    def health(self) -> dict[str, Any]: ...


class LLMNotConfiguredError(ConfigurationError):
    """Raised when a real provider is selected without the credentials it needs.

    Raised *before* any request is attempted, so a misconfigured deployment fails
    loudly at the point of use instead of returning a fabricated answer.
    """


INSUFFICIENT_EVIDENCE_TEXT = {
    "en": (
        "I could not find this in the knowledge base I have access to, so I will not guess. "
        "Try rephrasing the question, or check the crop guide for your crop. For a decision that affects your "
        "crop or money, please confirm with your local agriculture officer or Krishi Vigyan Kendra (KVK)."
    ),
    "mr": (
        "माझ्याकडे असलेल्या माहिती स्रोतांमध्ये हे सापडले नाही, म्हणून मी अंदाज लावणार नाही. "
        "प्रश्न वेगळ्या शब्दांत विचारा किंवा तुमच्या पिकाचे मार्गदर्शन पाहा. पिक किंवा पैशांशी संबंधित निर्णयासाठी "
        "स्थानिक कृषी अधिकारी किंवा कृषी विज्ञान केंद्र (KVK) यांच्याकडून खात्री करा."
    ),
    "hi": (
        "जो जानकारी मेरे पास उपलब्ध स्रोतों में है, उसमें यह नहीं मिला, इसलिए मैं अनुमान नहीं लगाऊँगा। "
        "प्रश्न दूसरे शब्दों में पूछें या अपनी फसल की गाइड देखें। फसल या पैसे से जुड़े निर्णय के लिए "
        "स्थानीय कृषि अधिकारी या कृषि विज्ञान केंद्र (KVK) से पुष्टि करें।"
    ),
}


def insufficient_evidence_text(language: str) -> str:
    return INSUFFICIENT_EVIDENCE_TEXT.get(language, INSUFFICIENT_EVIDENCE_TEXT["en"])


def extract_context_block(messages: list[LLMMessage]) -> str:
    """The retrieval pipeline puts evidence in a system message starting with
    `CONTEXT:`; this is the only text a grounded provider may use."""
    blocks = [
        message.content.partition(":")[2].strip()
        for message in messages
        if message.role == "system"
        and message.content.strip().upper().startswith("CONTEXT")
    ]
    return "\n\n".join(block for block in blocks if block)


def _keywords(text: str) -> set[str]:
    words = re.findall(r"[\w\u0900-\u097F]+", (text or "").lower())
    stop = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "how",
        "what",
        "when",
        "why",
        "i",
        "we",
        "my",
        "me",
        "of",
        "for",
        "to",
        "in",
        "on",
        "and",
        "or",
        "should",
        "can",
        "do",
        "does",
        "which",
        "with",
        "please",
        "tell",
        "about",
    }
    return {word for word in words if len(word) > 2 and word not in stop}


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?।])\s+", (text or "").strip())
    return [part.strip() for part in parts if len(part.strip()) > 25]


def _overlap(sentence: str, keywords: set[str]) -> float:
    words = set(re.findall(r"[\w\u0900-\u097F]+", sentence.lower()))
    if not words or not keywords:
        return 0.0
    return len(words & keywords) / max(1, len(keywords))


class MockLLMProvider:
    """Deterministic extractive summariser used when no LLM is configured.

    It is *not* a language model. It selects sentences from the retrieved
    evidence that overlap with the question, keeps them verbatim and labels them
    with the evidence block they came from. Nothing is paraphrased, so nothing can
    be invented — and every response says which provider produced it.
    """

    name = "mock"
    model = "extractive-summariser-v1"
    is_demo = True

    NOTICE = (
        "Extractive demo provider: this answer was assembled from the retrieved evidence by a rule-based "
        "summariser — no language model was involved. Set LLM_PROVIDER to use a real model."
    )

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResult:
        context = extract_context_block(messages)
        question = next((m.content for m in reversed(messages) if m.role == "user"), "")
        if not context:
            return LLMResult(
                text=insufficient_evidence_text("en"),
                provider=self.name,
                model=self.model,
                is_demo=True,
                notices=[
                    self.NOTICE,
                    "No evidence context was supplied, so the demo provider refused to answer (by design).",
                ],
                finish_reason="no_context",
            )

        blocks = re.split(r"\[EVIDENCE\s+(\d+):([^\]]*)\]", context)
        labelled: list[tuple[str, str]] = []  # (label, text)
        if len(blocks) >= 4:
            for index in range(1, len(blocks), 3):
                label = f"[{blocks[index]}] {blocks[index + 1].strip(' |')}"
                labelled.append((label, blocks[index + 2].strip()))
        else:
            labelled.append(("[CONTEXT]", context))

        keywords = _keywords(question)
        scored: list[tuple[float, str, str]] = []
        for label, text in labelled:
            for sentence in _split_sentences(text):
                score = _overlap(sentence, keywords)
                if score > 0:
                    scored.append((score, label, sentence))
        scored.sort(key=lambda item: (-item[0], item[1]))

        if not scored:
            label, text = labelled[0]
            excerpt = " ".join(_split_sentences(text)[:2]) or text[:300]
            return LLMResult(
                text=f"{label} {excerpt}",
                provider=self.name,
                model=self.model,
                is_demo=True,
                notices=[
                    self.NOTICE,
                    "No sentence in the retrieved evidence overlapped with the question: the closest passage "
                    "is quoted verbatim instead of an answer being composed.",
                ],
                finish_reason="extractive_fallback",
            )

        pieces = [f"{label} {sentence}" for _score, label, sentence in scored[:4]]
        return LLMResult(
            text=" ".join(pieces),
            provider=self.name,
            model=self.model,
            is_demo=True,
            notices=[self.NOTICE],
            finish_reason="extractive",
        )

    def health(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "model": self.model,
            "is_demo": True,
            "configured": True,
            "note": self.NOTICE,
        }


class OpenAICompatibleProvider:
    """OpenAI, Azure-style gateways, Ollama and most self-hosted serving stacks."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.base_url = (
            base_url or settings.llm_base_url or "https://api.openai.com/v1"
        ).rstrip("/")
        self.model = model or settings.llm_model or "gpt-4o-mini"
        self._api_key = api_key if api_key is not None else settings.llm_api_key
        self.name = (
            settings.llm_provider
            if settings.llm_provider in {"openai", "custom", "ollama"}
            else "openai"
        )
        self.is_demo = False

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResult:
        if self.name == "openai" and not self._api_key:
            raise LLMNotConfiguredError("LLM_PROVIDER=openai requires LLM_API_KEY.")
        import httpx

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": settings.llm_temperature
            if temperature is None
            else temperature,
            "max_tokens": max_tokens or settings.llm_max_output_tokens,
        }
        if json_schema:
            payload["response_format"] = {"type": "json_object"}
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
                timeout=settings.llm_timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            raise LLMNotConfiguredError(
                f"LLM request to {self.base_url} failed: {exc}"
            ) from exc
        if response.status_code >= 400:
            raise LLMNotConfiguredError(
                f"LLM provider returned HTTP {response.status_code}: {response.text[:200]}"
            )
        data = response.json()
        usage = data.get("usage") or {}
        choice = (data.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content", "") or ""
        LLM_TOKEN_COUNTER.labels(provider=self.name, kind="prompt").inc(
            usage.get("prompt_tokens", 0) or 0
        )
        LLM_TOKEN_COUNTER.labels(provider=self.name, kind="completion").inc(
            usage.get("completion_tokens", 0) or 0
        )
        return LLMResult(
            text=text,
            provider=self.name,
            model=self.model,
            is_demo=False,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            finish_reason=choice.get("finish_reason"),
            raw={"id": data.get("id")},
        )

    def health(self) -> dict[str, Any]:
        configured = bool(self._api_key) or self.name == "ollama"
        return {
            "provider": self.name,
            "model": self.model,
            "is_demo": False,
            "configured": configured,
            "base_url": self.base_url,
            "note": None if configured else "LLM_API_KEY is not set for this provider.",
        }


class AnthropicProvider:
    name = "anthropic"
    is_demo = False

    def __init__(self, *, model: str | None = None, api_key: str | None = None) -> None:
        self.model = model or settings.llm_model or "claude-3-5-sonnet-latest"
        self._api_key = api_key if api_key is not None else settings.llm_api_key
        if not self._api_key:
            raise LLMNotConfiguredError("LLM_PROVIDER=anthropic requires LLM_API_KEY.")

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResult:
        import httpx

        system = "\n\n".join(m.content for m in messages if m.role == "system")
        convo = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role in {"user", "assistant"}
        ]
        payload: dict[str, Any] = {
            "model": self.model,
            "system": system or None,
            "messages": convo,
            "max_tokens": max_tokens or settings.llm_max_output_tokens,
            "temperature": settings.llm_temperature
            if temperature is None
            else temperature,
        }
        try:
            response = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
                timeout=settings.llm_timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            raise LLMNotConfiguredError(f"Anthropic request failed: {exc}") from exc
        if response.status_code >= 400:
            raise LLMNotConfiguredError(
                f"Anthropic returned HTTP {response.status_code}: {response.text[:200]}"
            )
        data = response.json()
        text = "".join(block.get("text", "") for block in data.get("content", []))
        usage = data.get("usage") or {}
        LLM_TOKEN_COUNTER.labels(provider=self.name, kind="prompt").inc(
            usage.get("input_tokens", 0) or 0
        )
        LLM_TOKEN_COUNTER.labels(provider=self.name, kind="completion").inc(
            usage.get("output_tokens", 0) or 0
        )
        return LLMResult(
            text=text,
            provider=self.name,
            model=self.model,
            is_demo=False,
            prompt_tokens=usage.get("input_tokens"),
            completion_tokens=usage.get("output_tokens"),
            finish_reason=data.get("stop_reason"),
        )

    def health(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "model": self.model,
            "is_demo": False,
            "configured": True,
        }


def get_llm_provider() -> LLMProvider:
    provider = settings.llm_provider
    if provider == "anthropic":
        return AnthropicProvider()
    if provider in {"openai", "custom", "ollama"}:
        return OpenAICompatibleProvider()
    return MockLLMProvider()


def llm_health() -> dict[str, Any]:
    """Never raises: health endpoints must report misconfiguration, not crash."""
    try:
        return get_llm_provider().health()
    except LLMNotConfiguredError as exc:
        return {
            "provider": settings.llm_provider,
            "model": settings.llm_model or None,
            "is_demo": False,
            "configured": False,
            "note": str(exc),
        }


def extract_json(text: str) -> dict[str, Any] | None:
    """First JSON object in a model reply, or None.

    Tool-calling code must handle None (prose instead of a tool call) instead of
    treating arbitrary text as structured output.
    """
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None
