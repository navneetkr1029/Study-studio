"""Offline logic check: runs without fastapi/httpx by stubbing httpx. Run: python tests/offline_check.py"""
import asyncio, io, os, sys, types

try:
    import httpx  # noqa: F401
except ImportError:  # minimal stand-in so the module imports; the network is never used here
    _stub = types.ModuleType("httpx")
    _stub.AsyncClient = _stub.Timeout = type("Stub", (), {"__init__": lambda self, *a, **k: None})
    _stub.ConnectError = type("ConnectError", (Exception,), {})
    _stub.TimeoutException = type("TimeoutException", (Exception,), {})
    sys.modules["httpx"] = _stub
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import llm, pipeline, extractors, prompts  # noqa: E402
from app.config import settings  # noqa: E402

calls = {"gen": [], "img": []}

async def fake_generate(system, user):
    calls["gen"].append(user)
    return "- note" if user.startswith("Condense") else "FINAL ANSWER"

async def fake_image(data, mime, instruction):
    calls["img"].append(mime)
    return "Text read from image: photosynthesis"

llm.generate, llm.describe_image = fake_generate, fake_image

async def collect(**kw):
    return [e async for e in pipeline.run(**kw)]

def main():
    # chunker
    text = "Sentence one. Sentence two! " * 400 + "\n\n" + "x" * 12000 + "\n\nEnd paragraph."
    chunks = pipeline.chunk_text(text, 3000)
    assert all(len(c) <= 3000 for c in chunks)
    j = "".join(chunks)
    assert j.count("x") == 12000 and "End paragraph." in j
    print("chunker ok:", len(chunks), "chunks")

    # short text, every mode, single model call
    for mode in ["summary", "qa", "flashcards", "custom"]:
        calls["gen"].clear()
        ev = asyncio.run(collect(text="Cells are the unit of life.", mode=mode, custom="make a quiz"))
        assert ev[-1]["type"] == "result" and ev[-1]["condensed"] is False and len(calls["gen"]) == 1
    print("short text ok for all modes")

    # counts + level reach the prompt
    _, u = prompts.final_prompt("flashcards", "abc", count=12)
    assert "12 flashcards" in u
    _, u = prompts.final_prompt("qa", "abc", count=7, level="college")
    assert "7 question-and-answer pairs" in u and "college" in u
    print("prompt options ok")

    # custom prompt with no text
    ev = asyncio.run(collect(text="", mode="custom", custom="Explain gravity simply"))
    assert ev[-1]["type"] == "result"
    print("custom without text ok")

    # ~2 MB of text: no length limit
    para = "Photosynthesis converts light energy into chemical energy. " * 20
    big = "\n\n".join([para] * 1500)
    calls["gen"].clear()
    ev = asyncio.run(collect(text=big, mode="summary"))
    assert len(big) > 1_500_000
    assert ev[0]["type"] == "progress" and "Long text" in ev[0]["message"]
    assert ev[-1]["type"] == "result" and ev[-1]["condensed"] is True
    assert len(calls["gen"][-1]) < settings.single_pass_chars + 2000
    print(f"2MB text ok: {len(calls['gen'])} model calls, final prompt {len(calls['gen'][-1])} chars")

    # extractors
    r = asyncio.run(extractors.extract("a.txt", b"Hello study world", "text/plain"))
    assert r == "Hello study world"
    r = asyncio.run(extractors.extract("b.csv", b"term,definition\nmitosis,cell division\n", "text/csv"))
    assert "term: mitosis | definition: cell division" in r
    print("txt/csv ok")

    from reportlab.pdfgen import canvas
    buf = io.BytesIO(); c = canvas.Canvas(buf)
    c.drawString(72, 750, "The mitochondria is the powerhouse of the cell."); c.showPage()
    c.drawString(72, 750, "Page two talks about ribosomes and proteins."); c.save()
    calls["img"].clear()
    r = asyncio.run(extractors.extract("n.pdf", buf.getvalue(), "application/pdf"))
    assert "mitochondria" in r and "ribosomes" in r and not calls["img"]
    print("text PDF ok (no OCR used)")

    from PIL import Image
    buf = io.BytesIO(); Image.new("RGB", (300, 300), "white").save(buf, format="PDF")
    r = asyncio.run(extractors.extract("scan.pdf", buf.getvalue(), "application/pdf"))
    assert "photosynthesis" in r and calls["img"] == ["image/png"]
    print("scanned PDF -> vision fallback ok")

    buf = io.BytesIO(); Image.new("RGB", (40, 40), "white").save(buf, format="PNG")
    calls["img"].clear()
    r = asyncio.run(extractors.extract("n.png", buf.getvalue(), "image/png"))
    assert "photosynthesis" in r and calls["img"] == ["image/png"]
    print("image ok")

    for name, data, ct, expect in [("x.exe", b"MZ", "application/octet-stream", "Unsupported"),
                                   ("e.txt", b"   ", "text/plain", "No readable text"),
                                   ("bad.pdf", b"not a pdf", "application/pdf", "")]:
        try:
            asyncio.run(extractors.extract(name, data, ct)); raise SystemExit(f"{name}: expected error")
        except extractors.ExtractError as e:
            assert expect in str(e)
    print("error handling ok")
    print("ALL OFFLINE CHECKS PASSED")

main()
