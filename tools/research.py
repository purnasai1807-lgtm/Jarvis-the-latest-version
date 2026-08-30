"""
Background research worker.

Takes a free-form prompt ("find me the best 4K monitor under 2000 lei",
"research electric SUVs with >500km range", "compare Notion vs Obsidian for
research notes") and runs a multi-step pipeline:

  1. LLM expands the prompt into 2-3 distinct search queries
  2. web_search each → collect candidate URLs (deduped)
  3. read_page top N (with timeouts so a slow site doesn't kill the run)
  4. LLM summarises each page (sources stay attached)
  5. LLM synthesises a structured final answer with comparisons

Progress is streamed to the task log so the user can watch it on the mobile
TasksScreen. Total runtime cap ~6 minutes.

Registered with `core.tasks` as runner kind="research".
"""

from __future__ import annotations

import json
import time
from typing import Any

from loguru import logger

from core import tasks


_MAX_QUERIES = 3
_MAX_PAGES = 5
_MAX_PAGE_CHARS = 4000     # truncate page text before summarisation
_MAX_TOTAL_SECONDS = 360   # 6 min hard cap
_MAX_SUMMARY_TOKENS = 600
_MAX_FINAL_TOKENS = 900


# ── OpenAI helper ────────────────────────────────────────────────
def _llm(messages: list[dict], *, max_tokens: int = 600,
         json_mode: bool = False) -> str:
    """One-shot LLM call using whatever model the brain is configured for."""
    from core.config import load_config
    cfg = load_config()
    api_key = cfg.get("apis", {}).get("openai", {}).get("api_key", "")
    model = cfg.get("apis", {}).get("openai", {}).get("model", "gpt-4.1-mini")

    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    return (resp.choices[0].message.content or "").strip()


# ── Pipeline steps ───────────────────────────────────────────────
def _expand_queries(prompt: str) -> list[str]:
    """Use the LLM to turn one user prompt into 2-3 distinct search queries."""
    raw = _llm(
        [
            {"role": "system",
             "content": ("You expand a research prompt into 2-3 distinct, "
                         "diverse web-search queries that together will cover "
                         "the topic well. Reply with JSON: "
                         '{"queries": ["...", "..."]}.')},
            {"role": "user", "content": prompt},
        ],
        max_tokens=200, json_mode=True,
    )
    try:
        data = json.loads(raw)
        queries = [q.strip() for q in (data.get("queries") or []) if q.strip()]
        return queries[:_MAX_QUERIES] or [prompt]
    except Exception:
        return [prompt]


def _gather_urls(queries: list[str], task_id: int) -> list[tuple[str, str]]:
    """Run web_search for each query; return deduped list of (title, url)."""
    from tools.browser import web_search
    seen: set[str] = set()
    out: list[tuple[str, str]] = []

    for q in queries:
        if tasks.is_cancelled(task_id):
            return out
        tasks.append_log(task_id, f"🔎 search: {q}")
        try:
            text = web_search(q)
        except Exception as exc:
            tasks.append_log(task_id, f"  search error: {exc}")
            continue

        # web_search returns formatted text; pull URLs out heuristically
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("http"):
                continue
            url = line.split()[0]
            if url in seen:
                continue
            seen.add(url)
            out.append(("", url))
            if len(out) >= _MAX_PAGES * 2:
                break
        tasks.append_log(task_id, f"  → {len(seen)} unique URLs so far")

    return out[: _MAX_PAGES]


def _summarise_page(prompt: str, url: str, content: str) -> str:
    """Summarise a single page in the context of the user's research prompt."""
    truncated = content[:_MAX_PAGE_CHARS]
    return _llm(
        [
            {"role": "system",
             "content": ("You extract the key facts from a web page that are "
                         "relevant to the user's research prompt. Be concrete: "
                         "specific products, prices, specs, dates, names. "
                         "Skip generic marketing fluff. 4-8 bullet points max.")},
            {"role": "user",
             "content": (f"Research prompt: {prompt}\n"
                         f"Source URL: {url}\n\n"
                         f"Page content:\n{truncated}")},
        ],
        max_tokens=_MAX_SUMMARY_TOKENS,
    )


def _final_synthesis(prompt: str, summaries: list[dict]) -> str:
    """Combine all page summaries into the final structured answer."""
    formatted = []
    for i, s in enumerate(summaries, 1):
        formatted.append(f"## Source {i}: {s['url']}\n{s['summary']}")
    body = "\n\n".join(formatted)

    return _llm(
        [
            {"role": "system",
             "content": ("You synthesise multi-source research into a clean, "
                         "actionable answer for the user. Structure with "
                         "headers, bullets, and a short top-3 ranking when "
                         "relevant. Cite sources by their number [1], [2]. "
                         "Stay concrete — names, numbers, prices, links. "
                         "End with a 1-line bottom-line recommendation.")},
            {"role": "user",
             "content": f"Original prompt: {prompt}\n\nResearch:\n{body}"},
        ],
        max_tokens=_MAX_FINAL_TOKENS,
    )


# ── Public runner (registered with core.tasks) ───────────────────
def run_research(task_id: int, prompt: str) -> str:
    """Multi-step research pipeline. Returns the final synthesis string."""
    started = time.time()

    def _budget_ok() -> bool:
        return (time.time() - started) < _MAX_TOTAL_SECONDS

    tasks.append_log(task_id, f"⚙ planning queries for: {prompt}")
    queries = _expand_queries(prompt)
    tasks.append_log(task_id, f"  queries: {queries}")

    if tasks.is_cancelled(task_id) or not _budget_ok():
        return "Research cancelled or timed out before search."

    urls = _gather_urls(queries, task_id)
    if not urls:
        return "No usable URLs found from search."
    tasks.append_log(task_id, f"📑 fetching top {len(urls)} pages…")

    from tools.browser import read_page

    summaries: list[dict] = []
    for i, (_, url) in enumerate(urls, 1):
        if tasks.is_cancelled(task_id) or not _budget_ok():
            break
        tasks.append_log(task_id, f"  [{i}/{len(urls)}] reading {url[:80]}")
        try:
            content = read_page(url)
        except Exception as exc:
            tasks.append_log(task_id, f"    read error: {exc}")
            continue

        if not content or "Failed to read" in content[:60]:
            tasks.append_log(task_id, "    (skipped — empty/error)")
            continue

        try:
            summary = _summarise_page(prompt, url, content)
        except Exception as exc:
            tasks.append_log(task_id, f"    summary error: {exc}")
            continue

        summaries.append({"url": url, "summary": summary})
        tasks.append_log(task_id, f"    ✓ summarised ({len(summary)} chars)")

    if not summaries:
        return "Couldn't extract usable content from any source."

    if tasks.is_cancelled(task_id):
        return "Research cancelled mid-way."

    tasks.append_log(task_id, f"🧠 synthesising from {len(summaries)} sources…")
    final = _final_synthesis(prompt, summaries)
    tasks.append_log(task_id, "✅ done")
    return final


# ── Auto-register on import ──────────────────────────────────────
def register() -> None:
    tasks.register_runner("research", run_research)


register()
