import os
import json
import time
import random
from typing import Dict, Any, Optional, List

"""LLM integration module

Responsibilities:
- Define a clean interface to generate vocabulary info for a word
- Encapsulate Cerebras Cloud SDK usage
- Provide a deterministic mock fallback when an API key isn't configured

Public API:
- generate_word_info(word: str) -> Dict[str, Any]
"""

# -----------------------------
# Prompt and schema
# -----------------------------
SYSTEM_PROMPT = (
    "You are a precise English vocabulary assistant. "
    "Given a single English word, return a compact JSON object with: "
    "definition (one clear sentence), synonyms (3-8 items), antonyms (0-5 items), "
    "example (a complex, natural sentence), meaning_bn (Bengali translation of the word). "
    "Respond with JSON only, no extra text. Keys: definition, synonyms, antonyms, example, meaning_bn."
)

BATCH_SYSTEM_PROMPT = (
    "You are a precise English vocabulary assistant. "
    "Given a list of English words, return a JSON object where each key is the word "
    "and the value is an object with: definition (one clear sentence), synonyms (3-8 items), antonyms (0-5 items), "
    "example (a complex, natural sentence), meaning_bn (Bengali translation of the word). "
    "Respond with JSON only, no extra text. Keys per word: definition, synonyms, antonyms, example, meaning_bn."
)


def _mock_payload(word: str, source: str = "mock") -> Dict[str, Any]:
    """Return a deterministic mock payload for development and error fallbacks."""
    return {
        "definition": f"Definition for '{word}'.",
        "synonyms": [f"{word}_syn1", f"{word}_syn2"],
        "antonyms": [],
        "example": f"Here is a complex example sentence using the word {word} in context.",
        "meaning_bn": f"'{word}' শব্দের বাংলা অর্থ।",
        "_source": source,
    }


class CerebrasLLMClient:
    """Thin wrapper around the Cerebras Cloud SDK.

    Usage:
        client = CerebrasLLMClient.from_env()
        data = client.generate_word_info("example")
    """

    def __init__(self, api_key: Optional[str]):
        self.api_key = api_key
        self._client = None

    @classmethod
    def from_env(cls) -> "CerebrasLLMClient":
        return cls(api_key=os.environ.get("CEREBRAS_API_KEY"))

    def _ensure_client(self):
        if not self.api_key:
            return None
        if self._client is None:
            from cerebras.cloud.sdk import Cerebras  # lazy import
            self._client = Cerebras(api_key=self.api_key)
        return self._client

    def _extract_json(self, content: str) -> Dict[str, Any]:
        """Best-effort extraction of JSON from a model response.

        Accepts plain JSON or JSON inside Markdown fences. If parsing fails, raises ValueError.
        """
        if not isinstance(content, str):
            raise ValueError("content is not a string")
        s = content.strip()
        # Strip markdown code fences if present
        if s.startswith("```"):
            # remove leading triple backticks and language tag
            first_nl = s.find("\n")
            if first_nl != -1:
                s = s[first_nl + 1 :]
            if s.endswith("```"):
                s = s[: -3]
            s = s.strip()
        # If still not pure JSON, attempt to slice between first { and last }
        if not s.lstrip().startswith('{'):
            li = s.find('{')
            rj = s.rfind('}')
            if li != -1 and rj != -1 and rj > li:
                s = s[li : rj + 1]
        return json.loads(s)

    def _is_rate_limit_error(self, err: Exception) -> bool:
        name = type(err).__name__
        if 'RateLimit' in name:
            return True
        s = str(err)
        return ('rate limit' in s.lower()) or ('429' in s)

    def generate_word_info(self, word: str) -> Dict[str, Any]:
        """Generate vocabulary information for a single word.

        Returns a normalized dict with keys: definition, synonyms, antonyms, example, meaning_bn, _source.
        On missing key or error conditions, returns a mock payload instead of raising.
        """
        if not self.api_key:
            return _mock_payload(word, source="mock")

        try:
            client = self._ensure_client()
            model = os.environ.get("CEREBRAS_MODEL", "gpt-oss-120b")
            reasoning = os.environ.get("CEREBRAS_REASONING", "low")
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"word: {word}\nReturn JSON only."},
            ]
            # Retry with exponential backoff on rate limit
            retries = int(os.environ.get("CEREBRAS_RETRIES", "3"))
            base_delay = float(os.environ.get("CEREBRAS_BACKOFF_SECONDS", "0.6"))
            last_err: Optional[Exception] = None
            for attempt in range(retries + 1):
                try:
                    # Try a sequence of parameter sets to maximize compatibility across SDK/model combos
                    last_inner_err: Optional[Exception] = None
                    for params in (
                        # Streaming combo exactly like the user's sample (but with our prompt)
                        dict(model=model, stream=True, max_completion_tokens=65536, temperature=1, top_p=1, reasoning_effort=os.environ.get("CEREBRAS_REASONING", "medium")),
                        # Non-streaming variants (progressively simpler)
                        dict(model=model, stream=False, max_completion_tokens=1024, temperature=0.3, top_p=0.9, reasoning_effort=reasoning),
                        dict(model=model, stream=False, max_completion_tokens=1024, temperature=0.3, top_p=0.9),
                        dict(model=model, stream=False, temperature=0.3, top_p=0.9),
                        dict(model=model),
                    ):
                        try:
                            resp = client.chat.completions.create(messages=messages, **params)
                            # If this was a streaming call, accumulate content
                            if params.get('stream'):
                                parts: list[str] = []
                                for chunk in resp:
                                    try:
                                        delta = chunk.choices[0].delta
                                        piece = getattr(delta, 'content', None)
                                        if piece is None and isinstance(delta, dict):
                                            piece = delta.get('content')
                                    except Exception:
                                        piece = None
                                    if piece:
                                        parts.append(str(piece))
                                content = ''.join(parts)
                                class _Msg:
                                    def __init__(self, c): self.content = c
                                class _Resp:
                                    def __init__(self, txt): self.choices = [type('C', (), {'message': _Msg(txt)})()]
                                resp = _Resp(content)
                            # Parse content and return
                            msg = resp.choices[0].message
                            content = getattr(msg, 'content', None)
                            if isinstance(content, list):
                                content = ''.join(part.get('text', '') if isinstance(part, dict) else str(part) for part in content)
                            if content is None:
                                try:
                                    content = msg["content"]  # type: ignore[index]
                                except Exception:
                                    content = ""
                            data = self._extract_json(content)
                            data.setdefault("synonyms", [])
                            data.setdefault("antonyms", [])
                            data.setdefault("definition", "")
                            data.setdefault("example", "")
                            data.setdefault("meaning_bn", "")
                            data["_source"] = "cerebras"
                            return data
                        except TypeError as te:
                            last_inner_err = te
                            continue
                        except Exception as ex:
                            # If it's a rate limit, break to outer retry
                            if self._is_rate_limit_error(ex):
                                raise ex
                            last_inner_err = ex
                            continue
                    # If we exhausted all param combos without a return, raise last inner error
                    raise last_inner_err or RuntimeError("LLM call failed")
                except Exception as e:
                    last_err = e
                    if self._is_rate_limit_error(e) and attempt < retries:
                        # exponential backoff with jitter
                        delay = base_delay * (2 ** attempt) + random.uniform(0, 0.2)
                        time.sleep(delay)
                        continue
                    # otherwise, break out and handle below
                    break
            # After retries failed
            raise last_err or RuntimeError("LLM call failed after retries")

            # Extract text content from the first choice
            msg = resp.choices[0].message
            content = getattr(msg, 'content', None)
            if isinstance(content, list):
                # Some SDKs may return structured parts; join text pieces
                content = ''.join(part.get('text', '') if isinstance(part, dict) else str(part) for part in content)
            if content is None:
                # fallback to dict-style access
                try:
                    content = msg["content"]  # type: ignore[index]
                except Exception:
                    content = ""
            data = self._extract_json(content)
            # minimal normalization
            data.setdefault("synonyms", [])
            data.setdefault("antonyms", [])
            data.setdefault("definition", "")
            data.setdefault("example", "")
            data.setdefault("meaning_bn", "")
            data["_source"] = "cerebras"
            return data
        except Exception as e:  # noqa: BLE001 broad fallback
            # In strict mode (with a real key), bubble up errors instead of mocking.
            strict = str(os.environ.get("CEREBRAS_STRICT", "")).lower() in {"1", "true", "yes", "on"}
            if self.api_key and strict:
                raise
            # Fail safe with mock otherwise
            return _mock_payload(word, source=f"error:{type(e).__name__}")

    def generate_batch_word_info(self, words: List[str]) -> Dict[str, Dict[str, Any]]:
        """Generate vocabulary info for multiple words in one call.

        Returns a mapping of word -> data dict. On errors, honors strict mode; otherwise
        falls back to mock entries per word. Implements the same retry/backoff policy.
        """
        words = [w.strip() for w in words if isinstance(w, str) and w.strip()]
        if not words:
            return {}
        if not self.api_key:
            return {w: _mock_payload(w, source="mock") for w in words}

        try:
            client = self._ensure_client()
            model = os.environ.get("CEREBRAS_MODEL", "gpt-oss-120b")
            reasoning = os.environ.get("CEREBRAS_REASONING", "low")
            words_line = ", ".join(sorted(set(words)))
            messages = [
                {"role": "system", "content": BATCH_SYSTEM_PROMPT},
                {"role": "user", "content": f"words: [{words_line}]\nReturn JSON only keyed by the exact words."},
            ]
            retries = int(os.environ.get("CEREBRAS_RETRIES", "3"))
            base_delay = float(os.environ.get("CEREBRAS_BACKOFF_SECONDS", "0.6"))
            last_err: Optional[Exception] = None
            for attempt in range(retries + 1):
                try:
                    last_inner_err: Optional[Exception] = None
                    for params in (
                        dict(model=model, stream=True, max_completion_tokens=65536, temperature=1, top_p=1, reasoning_effort=os.environ.get("CEREBRAS_REASONING", "medium")),
                        dict(model=model, stream=False, max_completion_tokens=2048, temperature=0.3, top_p=0.9, reasoning_effort=reasoning),
                        dict(model=model, stream=False, max_completion_tokens=2048, temperature=0.3, top_p=0.9),
                        dict(model=model, stream=False, temperature=0.3, top_p=0.9),
                        dict(model=model),
                    ):
                        try:
                            resp = client.chat.completions.create(messages=messages, **params)
                            if params.get('stream'):
                                parts: list[str] = []
                                for chunk in resp:
                                    try:
                                        delta = chunk.choices[0].delta
                                        piece = getattr(delta, 'content', None)
                                        if piece is None and isinstance(delta, dict):
                                            piece = delta.get('content')
                                    except Exception:
                                        piece = None
                                    if piece:
                                        parts.append(str(piece))
                                content = ''.join(parts)
                                class _Msg:
                                    def __init__(self, c): self.content = c
                                class _Resp:
                                    def __init__(self, txt): self.choices = [type('C', (), {'message': _Msg(txt)})()]
                                resp = _Resp(content)
                            msg = resp.choices[0].message
                            content = getattr(msg, 'content', None)
                            if isinstance(content, list):
                                content = ''.join(part.get('text', '') if isinstance(part, dict) else str(part) for part in content)
                            if content is None:
                                try:
                                    content = msg["content"]  # type: ignore[index]
                                except Exception:
                                    content = ""
                            data = self._extract_json(content)
                            # Expect mapping word->object
                            if not isinstance(data, dict):
                                raise ValueError("Batch response is not an object")
                            out: Dict[str, Dict[str, Any]] = {}
                            for w in words:
                                item = data.get(w)
                                if isinstance(item, dict):
                                    item.setdefault("synonyms", [])
                                    item.setdefault("antonyms", [])
                                    item.setdefault("definition", "")
                                    item.setdefault("example", "")
                                    item.setdefault("meaning_bn", "")
                                    item["_source"] = "cerebras"
                                    out[w] = item
                                else:
                                    out[w] = _mock_payload(w, source="error:MissingEntry")
                            return out
                        except TypeError as te:
                            last_inner_err = te
                            continue
                        except Exception as ex:
                            if self._is_rate_limit_error(ex):
                                raise ex
                            last_inner_err = ex
                            continue
                    raise last_inner_err or RuntimeError("Batch LLM call failed")
                except Exception as e:
                    last_err = e
                    if self._is_rate_limit_error(e) and attempt < retries:
                        delay = base_delay * (2 ** attempt) + random.uniform(0, 0.2)
                        time.sleep(delay)
                        continue
                    break
            raise last_err or RuntimeError("Batch LLM call failed after retries")
        except Exception as e:  # noqa: BLE001
            strict = str(os.environ.get("CEREBRAS_STRICT", "")).lower() in {"1", "true", "yes", "on"}
            if self.api_key and strict:
                raise
            return {w: _mock_payload(w, source=f"error:{type(e).__name__}") for w in words}


# -----------------------------
# Functional facades
# -----------------------------


# -----------------------------
# Functional facade (backwards-compat)
# -----------------------------
def generate_word_info(word: str) -> Dict[str, Any]:
    """Backwards-compatible functional API.

    Delegates to CerebrasLLMClient.from_env().generate_word_info(word)
    so callers don't need to manage client instances.
    """
    client = CerebrasLLMClient.from_env()
    return client.generate_word_info(word)

def generate_batch_word_info(words: List[str]) -> Dict[str, Dict[str, Any]]:
    client = CerebrasLLMClient.from_env()
    return client.generate_batch_word_info(words)
