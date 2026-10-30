"""
BaseAgent
=========
Shared plumbing for every agent in the prototype:

- Model routing (cheap vs strong) driven by env vars.
- A single ``call`` method that wraps the Anthropic SDK with retry.
- Robust JSON parsing that tolerates markdown-fenced / prose-wrapped JSON.
- DEMO_MODE: when enabled, no network calls are made. Each subclass supplies a
  ``demo_response`` so the whole app is runnable with no API key.
- Structured error output: every failure is returned as a JSON-serialisable
  dict (never an exception bubbling into the UI).

Design principle preserved from the reference project: keep cost low. Narrow,
structured tasks (extraction, surgical revision) route to the cheap model;
only novel synthesis and safety-critical review route to the strong model.
"""

from __future__ import annotations

import json
import os
import re
import time
import traceback
from datetime import datetime
from typing import Any, Dict, Optional


def _env(name: str, default: str = "") -> str:
    val = os.environ.get(name)
    return val if val not in (None, "") else default


def utc_timestamp() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


class BaseAgent:
    """Base class for all agents.

    Subclasses set ``name`` and implement ``demo_response(payload)`` so the
    agent works in DEMO_MODE.  Subclasses typically expose a public method
    (e.g. ``parse`` / ``generate`` / ``revise``) that builds a prompt and calls
    ``self.run(...)``.
    """

    name: str = "Base Agent"
    #: which model tier this agent prefers: "cheap" or "strong"
    tier: str = "cheap"
    #: short role key used for per-agent provider/model overrides
    #: (e.g. role="protocol" -> env PROTOCOL_PROVIDER / PROTOCOL_MODEL)
    role: str = ""

    def __init__(self, tier: Optional[str] = None) -> None:
        if tier:
            self.tier = tier
        self.demo_mode = _env("DEMO_MODE", "true").lower() in ("1", "true", "yes", "on")
        # provider: per-agent override (<ROLE>_PROVIDER) else global LLM_PROVIDER.
        role_up = (self.role or "").upper()
        self.provider = (
            (_env(f"{role_up}_PROVIDER") if role_up else "")
            or _env("LLM_PROVIDER", "openai")
        ).lower()
        # optional exact-model override for this agent (<ROLE>_MODEL); wins over
        # tier/provider defaults and FORCE_CHEAP.
        self.role_model = _env(f"{role_up}_MODEL") if role_up else ""
        # FORCE_CHEAP makes every agent use the cheap model (e.g. Haiku-only) to
        # keep cost minimal — strong-tier agents are downgraded to cheap.
        self.force_cheap = _env("FORCE_CHEAP", "false").lower() in ("1", "true", "yes", "on")

        # model names per provider/tier
        self.anthropic_cheap = _env("ANTHROPIC_CHEAP_MODEL", "claude-haiku-4-5-20251001")
        self.anthropic_strong = _env("ANTHROPIC_STRONG_MODEL", "claude-sonnet-4-6")
        self.openai_cheap = _env("OPENAI_CHEAP_MODEL", "gpt-4o-mini")
        self.openai_strong = _env("OPENAI_STRONG_MODEL", "gpt-4o")

        self.anthropic_key = _env("ANTHROPIC_API_KEY")
        self.openai_key = _env("OPENAI_API_KEY")
        self._client = None  # lazily created

    # ------------------------------------------------------------------ #
    # Model routing
    # ------------------------------------------------------------------ #
    @property
    def effective_tier(self) -> str:
        # STRONG_ROLES is an allowlist of heavy authoring agents (e.g. "design,expdesign,protocol")
        # that use the STRONG model even when FORCE_CHEAP keeps everyone else on the cheap one —
        # the "balanced" posture: pay for reasoning where it matters, stay cheap elsewhere.
        strong_roles = {r.strip().lower() for r in _env("STRONG_ROLES", "").split(",") if r.strip()}
        if (self.role or "").lower() in strong_roles:
            return "strong"
        return "cheap" if self.force_cheap else self.tier

    @property
    def model(self) -> str:
        if self.role_model:
            return self.role_model
        strong = self.effective_tier == "strong"
        if self.provider == "openai":
            return self.openai_strong if strong else self.openai_cheap
        return self.anthropic_strong if strong else self.anthropic_cheap

    @property
    def api_key(self) -> str:
        return self.openai_key if self.provider == "openai" else self.anthropic_key

    # ------------------------------------------------------------------ #
    # Anthropic client (lazy)
    # ------------------------------------------------------------------ #
    def _get_client(self):
        if self._client is not None:
            return self._client
        if self.provider == "openai":
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError(
                    "openai package not installed. Run: pip install openai"
                ) from exc
            if not self.openai_key:
                raise RuntimeError(
                    "OPENAI_API_KEY is not set. Set DEMO_MODE=true or provide a key."
                )
            self._client = OpenAI(api_key=self.openai_key)
            return self._client
        # default: anthropic
        try:
            from anthropic import Anthropic
        except ImportError as exc:  # pragma: no cover - import guard
            raise RuntimeError(
                "anthropic package not installed. Run: pip install -r requirements.txt"
            ) from exc
        if not self.anthropic_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Set DEMO_MODE=true or provide a key."
            )
        self._client = Anthropic(api_key=self.anthropic_key)
        return self._client

    # ------------------------------------------------------------------ #
    # Low-level Claude call with retry
    # ------------------------------------------------------------------ #
    def call(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
        retries: int = 3,
        tools: Optional[list] = None,
        json_mode: bool = False,
    ) -> str:
        """Return raw text from the model. Retries on transient errors.

        ``tools`` may include Anthropic server tools such as web search.
        ``json_mode`` coerces a strict JSON object response: OpenAI uses its
        native JSON response_format; Anthropic uses an assistant '{' prefill."""
        client = self._get_client()
        last_err: Optional[Exception] = None
        for attempt in range(1, retries + 1):
            try:
                if self.provider == "openai":
                    messages = []
                    if system:
                        messages.append({"role": "system", "content": system})
                    messages.append({"role": "user", "content": prompt})
                    okwargs: Dict[str, Any] = dict(
                        model=self.model, messages=messages,
                        temperature=temperature, max_tokens=max_tokens,
                    )
                    if json_mode:
                        okwargs["response_format"] = {"type": "json_object"}
                    resp = client.chat.completions.create(**okwargs)
                    return (resp.choices[0].message.content or "").strip()
                # default: anthropic
                a_messages = [{"role": "user", "content": prompt}]
                if json_mode and not tools:
                    # prefill the assistant turn with '{' so the model emits JSON
                    a_messages.append({"role": "assistant", "content": "{"})
                kwargs: Dict[str, Any] = dict(
                    model=self.model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    messages=a_messages,
                )
                if system:
                    kwargs["system"] = system
                if tools:
                    kwargs["tools"] = tools
                resp = client.messages.create(**kwargs)
                parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
                text = "\n".join(parts).strip()
                # if we prefilled the assistant with '{', restore it
                if json_mode and not tools and not text.lstrip().startswith("{"):
                    text = "{" + text
                return text
            except Exception as exc:  # noqa: BLE001 - surface after retries
                last_err = exc
                if attempt < retries:
                    time.sleep(min(2 ** attempt, 8))
                continue
        raise RuntimeError(f"Claude call failed after {retries} attempts: {last_err}")

    # ------------------------------------------------------------------ #
    # JSON parsing helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def extract_json(text: str) -> Dict[str, Any]:
        """Parse JSON from a model response that may be markdown-wrapped or
        surrounded by prose. Raises ValueError if nothing parseable is found."""
        if text is None:
            raise ValueError("empty model response")
        text = text.strip()

        # 1. fenced ```json ... ``` block
        fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
        candidates = []
        if fence:
            candidates.append(fence.group(1).strip())
        # 2. raw text as-is
        candidates.append(text)
        # 3. first balanced { ... } object
        brace = BaseAgent._first_json_object(text)
        if brace:
            candidates.append(brace)
        # 4. salvage a truncated object: from first '{' to the last '}'
        s, e = text.find("{"), text.rfind("}")
        if s != -1 and e > s:
            candidates.append(text[s:e + 1])
        # 5. last resort: auto-close a truncated object (balance braces/brackets)
        if s != -1:
            ac = BaseAgent._autoclose(text[s:])
            if ac:
                candidates.append(ac)

        for cand in candidates:
            for variant in (cand, BaseAgent._relax_json(cand)):
                try:
                    return json.loads(variant)
                except Exception:
                    continue
        raise ValueError("no valid JSON found in model response")

    @staticmethod
    def _autoclose(s: str) -> Optional[str]:
        """Balance an unterminated JSON object from truncated output: close any
        open string, drop dangling key/colon/comma fragments, and append the
        missing }/] in the right order. Best-effort."""
        stack = []
        in_str = False
        esc = False
        for ch in s:
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch in "{[":
                    stack.append(ch)
                elif ch in "}]":
                    if stack:
                        stack.pop()
        if not stack and not in_str:
            return None  # nothing to fix
        out = s
        if in_str:
            if out.endswith("\\"):       # truncated on an escape char
                out = out[:-1]
            out += '"'
        out = out.rstrip()
        # strip trailing incomplete fragments. A trailing "..." preceded by ':'
        # is a real VALUE and must be kept; one preceded by ',' or '{' is a
        # dangling key and is removed.
        prev = None
        while prev != out:
            prev = out
            out = re.sub(r",\s*$", "", out).rstrip()                       # trailing comma
            out = re.sub(r":\s*$", "", out).rstrip()                       # colon w/o value
            out = re.sub(r',\s*"(?:[^"\\]|\\.)*"\s*$', "", out).rstrip()   # , "danglingKey"
            out = re.sub(r'(\{)\s*"(?:[^"\\]|\\.)*"\s*$', r"\1", out).rstrip()  # { "danglingKey"
        for opener in reversed(stack):
            out += "}" if opener == "{" else "]"
        return out

    @staticmethod
    def _relax_json(s: str) -> str:
        """Best-effort cleanup: strip // and /* */ comments and trailing commas."""
        s = re.sub(r"/\*.*?\*/", "", s, flags=re.DOTALL)
        s = re.sub(r"(^|\s)//[^\n]*", r"\1", s)
        s = re.sub(r",(\s*[}\]])", r"\1", s)  # trailing commas
        return s.strip()

    @staticmethod
    def _first_json_object(text: str) -> Optional[str]:
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return text[start : i + 1]
        return None

    # ------------------------------------------------------------------ #
    # High-level run: prompt -> JSON dict (or structured error)
    # ------------------------------------------------------------------ #
    def run(
        self,
        prompt: str,
        payload: Dict[str, Any],
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> Dict[str, Any]:
        """Execute the agent. In DEMO_MODE returns ``demo_response(payload)``.
        Otherwise calls Claude and parses JSON. Always returns a dict."""
        try:
            if self.demo_mode:
                result = self.demo_response(payload)
            else:
                raw = self.call(
                    prompt, system=system, max_tokens=max_tokens,
                    temperature=temperature, json_mode=True,
                )
                try:
                    result = self.extract_json(raw)
                except Exception as pe:
                    preview = (raw or "").strip().replace("\n", " ")[:400]
                    return self.error(
                        f"Could not parse model JSON via {self.provider}/{self.model} "
                        f"({pe}). Model returned: {preview!r}"
                    )
            # annotate provenance without clobbering agent-set fields
            result.setdefault("agent", self.name)
            result.setdefault("status", "success")
            result.setdefault("timestamp", utc_timestamp())
            result["_meta"] = {
                "model": "demo" if self.demo_mode else self.model,
                "demo_mode": self.demo_mode,
                "tier": self.tier,
            }
            return result
        except Exception as exc:  # noqa: BLE001
            return self.error(str(exc), trace=traceback.format_exc())

    # ------------------------------------------------------------------ #
    # Structured error
    # ------------------------------------------------------------------ #
    def error(self, message: str, trace: str = "") -> Dict[str, Any]:
        return {
            "agent": self.name,
            "status": "error",
            "error": message,
            "trace": trace,
            "timestamp": utc_timestamp(),
            "_meta": {"model": "demo" if self.demo_mode else self.model, "tier": self.tier},
        }

    # ------------------------------------------------------------------ #
    # Subclasses must implement a demo fallback
    # ------------------------------------------------------------------ #
    def demo_response(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # pragma: no cover
        raise NotImplementedError(f"{self.name} has no demo_response()")

    # ------------------------------------------------------------------ #
    # Prompt template loading
    # ------------------------------------------------------------------ #
    @staticmethod
    def load_prompt(filename: str, **fields: Any) -> str:
        """Load a prompt template from ../prompts and substitute ``{field}``
        placeholders. Missing placeholders are left intact."""
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(here, "prompts", filename)
        with open(path, "r", encoding="utf-8") as fh:
            template = fh.read()
        for key, value in fields.items():
            if not isinstance(value, str):
                value = json.dumps(value, indent=2, ensure_ascii=False)
            template = template.replace("{" + key + "}", value)
        return template
