"""Prompt templates for every output type."""
from typing import Optional, Tuple

SYSTEM = (
    "You are a careful educational assistant. Base your answer ONLY on the study material you are "
    "given; if the material does not cover something, say so instead of inventing facts. "
    "Write clear, well-organised Markdown."
)

MAP_SYSTEM = (
    "You are a meticulous note-taker. You condense one part of a longer text into faithful study "
    "notes. Never add information that is not in the text."
)


def map_prompt(part: str, focus: str = "") -> str:
    focus_line = f"\nThe reader especially cares about: {focus}\n" if focus.strip() else ""
    return (
        "Condense the following part of a longer study text into concise bullet-point notes. "
        "Keep every key concept, definition, name, date, formula and relationship; drop filler."
        f"{focus_line}\nTEXT:\n{part}\n\nNOTES:"
    )


def final_prompt(
    mode: str,
    material: str,
    level: str = "high school",
    count: Optional[int] = None,
    custom: str = "",
    condensed: bool = False,
) -> Tuple[str, str]:
    """Return (system, user) prompts for the final generation step."""
    material_label = (
        "STUDY NOTES (condensed from a longer text)" if condensed else "STUDY MATERIAL"
    )
    block = f"\n\n{material_label}:\n{material}\n" if material.strip() else ""

    if mode == "summary":
        task = (
            f"Summarize the study material for a {level} student. Start with a short overview "
            "paragraph, then list the key concepts and how they relate to each other."
        )
    elif mode == "qa":
        n = count or 5
        task = (
            f"Write {n} question-and-answer pairs for a {level} study guide that cover the most important "
            "ideas in the material. Format every pair exactly as:\n\n"
            "**Q1:** the question\n**A1:** the answer\n\n(and so on, numbering each pair)."
        )
    elif mode == "flashcards":
        n = count or 5
        task = (
            f"Create {n} flashcards for a {level} student from the material. Output ONLY the flashcards, "
            "each in exactly this format, separated by a blank line:\n\n"
            "Front: the concept or question\nBack: the definition or answer"
        )
    else:  # custom
        task = (custom or "").strip() or "Help me study this material."
        task = f"Follow this request from the student (explain at a {level} level unless told otherwise):\n{task}"

    return SYSTEM, f"{task}{block}"
