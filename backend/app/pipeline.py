"""Generation pipeline with no input-length limit.

Short text is sent to the model in a single call. Longer text is split into chunks, each chunk is
condensed into notes (map step), and the notes are condensed again until they fit in one call
(reduce step). The final study material is then generated from those notes.
"""
import asyncio
import re
from typing import AsyncIterator, List, Optional

from . import llm, prompts
from .config import settings

MAX_REDUCE_ROUNDS = 8


# ----------------------------------------------------------------------------------
# Chunking
# ----------------------------------------------------------------------------------
def _split_long(block: str, size: int) -> List[str]:
    """Split one oversized paragraph on sentence boundaries, then hard-cut anything still too long."""
    out: List[str] = []
    cur = ""
    for sent in re.split(r"(?<=[.!?])\s+", block):
        while len(sent) > size:
            if cur:
                out.append(cur)
                cur = ""
            out.append(sent[:size])
            sent = sent[size:]
        if cur and len(cur) + len(sent) + 1 > size:
            out.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}" if cur else sent
    if cur:
        out.append(cur)
    return out


def chunk_text(text: str, size: int) -> List[str]:
    """Split text into chunks of at most `size` characters, preferring paragraph boundaries."""
    pieces: List[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        pieces.extend([para] if len(para) <= size else _split_long(para, size))

    chunks: List[str] = []
    cur = ""
    for piece in pieces:
        if cur and len(cur) + len(piece) + 2 > size:
            chunks.append(cur)
            cur = piece
        else:
            cur = f"{cur}\n\n{piece}" if cur else piece
    if cur:
        chunks.append(cur)
    return chunks


# ----------------------------------------------------------------------------------
# Map / reduce
# ----------------------------------------------------------------------------------
async def _condense(parts: List[str], focus: str, label: str) -> AsyncIterator[dict]:
    """Condense every part into notes. Yields progress events, then one {"type": "_notes"} event."""
    sem = asyncio.Semaphore(max(1, settings.map_concurrency))
    results: List[Optional[str]] = [None] * len(parts)

    async def work(i: int, part: str) -> None:
        async with sem:
            results[i] = await llm.generate(prompts.MAP_SYSTEM, prompts.map_prompt(part, focus))

    tasks = [asyncio.create_task(work(i, p)) for i, p in enumerate(parts)]
    done = 0
    try:
        for fut in asyncio.as_completed(tasks):
            await fut
            done += 1
            yield {"type": "progress", "message": f"{label} {done}/{len(parts)}", "done": done, "total": len(parts)}
    finally:
        for t in tasks:
            t.cancel()
    yield {"type": "_notes", "notes": results}


async def run(
    text: str,
    mode: str,
    level: str = "high school",
    count: Optional[int] = None,
    custom: str = "",
) -> AsyncIterator[dict]:
    """Yield progress events followed by a single result event."""
    text = text.strip()
    material = text
    condensed = False
    focus = custom if mode == "custom" else ""

    if len(text) > settings.single_pass_chars:
        condensed = True
        parts = chunk_text(text, settings.chunk_chars)
        yield {"type": "progress", "message": f"Long text detected, reading it in {len(parts)} parts"}

        for round_no in range(1, MAX_REDUCE_ROUNDS + 1):
            label = "Reading part" if round_no == 1 else "Condensing notes, pass %d:" % round_no
            notes_list: List[Optional[str]] = []
            async for ev in _condense(parts, focus, label):
                if ev["type"] == "_notes":
                    notes_list = ev["notes"]
                else:
                    yield ev
            material = "\n\n".join(n.strip() for n in notes_list if n and n.strip())
            if not material:
                raise llm.LLMError("The model returned no notes for this text. Please try again.")
            if len(material) <= settings.single_pass_chars:
                break
            next_parts = chunk_text(material, settings.chunk_chars)
            if len(next_parts) >= len(parts):  # not shrinking any more; stop looping
                break
            parts = next_parts

    label = {"summary": "summary", "qa": "Q&A set", "flashcards": "flashcards"}.get(mode, "answer")
    yield {"type": "progress", "message": f"Writing your {label}"}
    system, user = prompts.final_prompt(mode, material, level=level, count=count, custom=custom, condensed=condensed)
    result = await llm.generate(system, user)
    if not result.strip():
        raise llm.LLMError("The model returned an empty answer. Please try again.")
    yield {"type": "result", "content": result, "condensed": condensed}
