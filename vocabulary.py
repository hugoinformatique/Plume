"""User correction dictionary for Plume.

Two jobs:
  1. Bias recognition: feed the correct technical terms to Whisper as
     ``hotwords`` / ``initial_prompt`` so it spells them right in the first place.
  2. Post-correction: replace known mis-hearings ("kubernét" -> "Kubernetes")
     and normalise the casing of known terms in the final text.

Each entry is {"from": <heard, optional>, "to": <correct term>}.
"""

from __future__ import annotations

import re


class Vocabulary:
    def __init__(self, entries: list[dict] | None = None) -> None:
        self.entries = [e for e in (entries or []) if e.get("to")]

    def to_list(self) -> list[dict]:
        return self.entries

    def add(self, heard: str, correct: str) -> None:
        heard = (heard or "").strip()
        correct = (correct or "").strip()
        if not correct:
            return
        # de-dup on (from, to)
        for e in self.entries:
            if e.get("from", "") == heard and e.get("to") == correct:
                return
        self.entries.insert(0, {"from": heard, "to": correct})

    def remove(self, index: int) -> None:
        if 0 <= index < len(self.entries):
            self.entries.pop(index)

    # --- biasing -------------------------------------------------------------
    def terms(self) -> list[str]:
        seen, out = set(), []
        for e in self.entries:
            t = e["to"]
            if t.lower() not in seen:
                seen.add(t.lower())
                out.append(t)
        return out

    def hotwords(self) -> str:
        """Space-joined correct terms for faster-whisper ``hotwords``."""
        return " ".join(self.terms())

    def initial_prompt(self) -> str:
        terms = self.terms()
        if not terms:
            return ""
        return "Vocabulaire : " + ", ".join(terms) + "."

    # --- post-correction -----------------------------------------------------
    def apply(self, text: str) -> str:
        if not text:
            return text
        # 1) explicit heard -> correct replacements
        for e in self.entries:
            heard = e.get("from", "").strip()
            if heard:
                text = re.sub(
                    r"\b" + re.escape(heard) + r"\b", e["to"], text, flags=re.IGNORECASE
                )
        # 2) normalise casing of known correct terms
        for term in self.terms():
            text = re.sub(
                r"\b" + re.escape(term) + r"\b",
                lambda _m, t=term: t,
                text,
                flags=re.IGNORECASE,
            )
        return text
