"""End-to-end API tests with the language model mocked out."""
import io
import json
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import extractors, llm, pipeline  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


@pytest.fixture
def fake_llm(monkeypatch):
    calls = {"generate": [], "image": []}

    async def generate(system, user):
        calls["generate"].append(user)
        if user.startswith("Condense"):
            return "- note"
        return "FINAL ANSWER"

    async def describe_image(data, mime, instruction):
        calls["image"].append(mime)
        return "Text read from image: photosynthesis"

    monkeypatch.setattr(llm, "generate", generate)
    monkeypatch.setattr(llm, "describe_image", describe_image)
    return calls


def stream(payload):
    r = client.post("/api/generate", json=payload)
    assert r.status_code == 200, r.text
    return [json.loads(line) for line in r.text.splitlines() if line.strip()]


# ---------- extraction ----------
def test_extract_txt_and_csv(fake_llm):
    csv_bytes = b"term,definition\nmitosis,cell division\natom,smallest unit\n"
    r = client.post(
        "/api/extract",
        files=[("files", ("a.txt", b"Hello study world", "text/plain")), ("files", ("b.csv", csv_bytes, "text/csv"))],
    )
    files = r.json()["files"]
    assert files[0]["text"] == "Hello study world"
    assert "term: mitosis | definition: cell division" in files[1]["text"]


def test_extract_pdf(fake_llm):
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 750, "The mitochondria is the powerhouse of the cell.")
    c.showPage()
    c.drawString(72, 750, "Page two talks about ribosomes and proteins.")
    c.save()
    r = client.post("/api/extract", files=[("files", ("n.pdf", buf.getvalue(), "application/pdf"))])
    text = r.json()["files"][0]["text"]
    assert "mitochondria" in text and "ribosomes" in text
    assert not fake_llm["image"]  # text layer was used, no OCR


def test_extract_scanned_pdf_falls_back_to_vision(fake_llm):
    from PIL import Image

    img = Image.new("RGB", (300, 300), "white")
    buf = io.BytesIO()
    img.save(buf, format="PDF")  # image-only PDF, no text layer
    r = client.post("/api/extract", files=[("files", ("scan.pdf", buf.getvalue(), "application/pdf"))])
    assert "photosynthesis" in r.json()["files"][0]["text"]
    assert fake_llm["image"] == ["image/png"]


def test_extract_image(fake_llm):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, format="PNG")
    r = client.post("/api/extract", files=[("files", ("n.png", buf.getvalue(), "image/png"))])
    assert "photosynthesis" in r.json()["files"][0]["text"]
    assert fake_llm["image"] == ["image/png"]


def test_extract_errors(fake_llm):
    r = client.post("/api/extract", files=[("files", ("x.exe", b"MZ", "application/octet-stream"))])
    assert "Unsupported" in r.json()["files"][0]["error"]
    r = client.post("/api/extract", files=[("files", ("e.txt", b"   ", "text/plain"))])
    assert "No readable text" in r.json()["files"][0]["error"]
    r = client.post("/api/extract", files=[("files", ("bad.pdf", b"not a pdf", "application/pdf"))])
    assert "error" in r.json()["files"][0]


# ---------- generation ----------
@pytest.mark.parametrize("mode", ["summary", "qa", "flashcards", "custom"])
def test_generate_short_text(fake_llm, mode):
    events = stream({"text": "Cells are the unit of life.", "mode": mode, "prompt": "make a quiz"})
    assert events[-1]["type"] == "result"
    assert events[-1]["content"] == "FINAL ANSWER"
    assert events[-1]["condensed"] is False
    assert len(fake_llm["generate"]) == 1


def test_flashcard_and_qa_counts_in_prompt(fake_llm):
    stream({"text": "abc", "mode": "flashcards", "count": 12})
    stream({"text": "abc", "mode": "qa", "count": 7, "level": "college"})
    assert "12 flashcards" in fake_llm["generate"][0]
    assert "7 question-and-answer pairs" in fake_llm["generate"][1] and "college" in fake_llm["generate"][1]


def test_custom_without_text_is_allowed(fake_llm):
    events = stream({"text": "", "mode": "custom", "prompt": "Explain gravity simply"})
    assert events[-1]["type"] == "result"


def test_long_text_has_no_length_limit(fake_llm):
    # ~2 million characters, far beyond any single model context
    para = "Photosynthesis converts light energy into chemical energy. " * 20
    text = "\n\n".join([para] * 1500)
    assert len(text) > 1_500_000
    events = stream({"text": text, "mode": "summary"})
    assert events[0]["type"] == "progress" and "Long text" in events[0]["message"]
    assert events[-1]["type"] == "result" and events[-1]["condensed"] is True
    # The final call must fit in one model call
    assert len(fake_llm["generate"][-1]) < settings.single_pass_chars + 2000


def test_validation(fake_llm):
    assert client.post("/api/generate", json={"text": "  ", "mode": "summary"}).status_code == 422
    assert client.post("/api/generate", json={"mode": "custom", "prompt": " "}).status_code == 422
    assert client.post("/api/generate", json={"text": "x", "mode": "bogus"}).status_code == 422


def test_llm_error_is_streamed_as_event(monkeypatch):
    async def boom(system, user):
        raise llm.LLMError("Cannot reach Ollama")

    monkeypatch.setattr(llm, "generate", boom)
    events = stream({"text": "hello", "mode": "summary"})
    assert events == [
        {"type": "progress", "message": "Writing your summary"},
        {"type": "error", "message": "Cannot reach Ollama"},
    ]


# ---------- chunking ----------
def test_chunker_respects_size_and_loses_nothing():
    text = "Sentence one. Sentence two! " * 400 + "\n\n" + "x" * 12000 + "\n\nEnd paragraph."
    chunks = pipeline.chunk_text(text, 3000)
    assert all(len(c) <= 3000 for c in chunks)
    joined = "".join(chunks)
    assert joined.count("x") == 12000 and "End paragraph." in joined


def test_health_endpoint(monkeypatch):
    async def fake_health():
        return {"provider": "ollama", "reachable": False}

    monkeypatch.setattr(llm, "health", fake_health)
    assert client.get("/api/health").json()["reachable"] is False
