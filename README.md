# Study Studio

Turn notes, PDFs and images into **summaries, Q&A sets, flashcards**, or anything you type a request for.
This is the Streamlit app rebuilt as a separate **backend (FastAPI)** and **frontend (plain HTML/CSS/JS)**,
so each part can be deployed on Vercel on its own.

```
study-studio/
├── backend/                 FastAPI API (deploy as its own Vercel project)
│   ├── app/
│   │   ├── main.py          routes: /api/health, /api/extract, /api/generate
│   │   ├── pipeline.py      unlimited-length text handling (chunk -> condense -> generate)
│   │   ├── extractors.py    PDF / image / CSV / TXT -> text
│   │   ├── llm.py           Ollama + OpenAI-compatible clients
│   │   ├── prompts.py       prompts for each output type
│   │   └── config.py        settings from environment variables
│   ├── api/index.py         Vercel entry point
│   ├── vercel.json
│   ├── requirements.txt     (no old pins, works on Python 3.14)
│   ├── .env.example
│   └── tests/
└── frontend/                static site (deploy as its own Vercel project)
    ├── index.html  style.css  app.js
    └── config.js            <- set your backend URL here
```

## What changed from the Streamlit version

| Before | Now |
|---|---|
| Streamlit UI | Separate HTML/CSS/JS frontend and FastAPI backend |
| CSV + TXT only | **PDF, TXT, MD, CSV and images** (PNG/JPG/WEBP). Scanned PDFs are read with the vision model |
| Upload only | Large **text box** to type or paste notes; uploaded text is added to it so you can edit it |
| Retrieval of only the top 4 chunks | **No length limit.** Long text is split, condensed into notes, then used to generate the result, so the whole text is used |
| Chroma + sentence-transformers + LangChain | Removed. They were the main Python 3.14 blockers and are too big for Vercel. The chunk-and-condense approach needs none of them |
| Ollama only | Ollama **or** any OpenAI-compatible API (OpenAI, Groq, OpenRouter, ...) |
| "Combined" mode | **Custom** mode: type any request, with or without study text |

Also new: choose the level (middle school to expert), choose how many Q&A pairs or flashcards, flip-card flashcards, copy and download as Markdown, a Stop button, and a status badge showing whether the model is reachable.

## Run it locally

You need Python 3.10+ (3.14 is fine) and, for the free local option, [Ollama](https://ollama.com).

```bash
# 1. Model(s)
ollama serve                 # if it is not already running
ollama pull phi3:mini        # text
ollama pull llava            # optional: reads images and scanned PDFs

# 2. Backend
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # edit if you want a different model
uvicorn app.main:app --reload --port 8000

# 3. Frontend (second terminal)
cd frontend
python -m http.server 5173
# open http://localhost:5173
```

`frontend/config.js` already points to `http://localhost:8000`.

## Deploy on Vercel

**Important:** Vercel's servers cannot reach Ollama running on your computer. For the deployed backend, use a hosted
model through the OpenAI-compatible settings (OpenAI, Groq, OpenRouter, ...). Ollama stays an option for local use.

1. **Backend**: in Vercel, import the repo and set **Root Directory** to `backend`. Add environment variables:
   ```
   LLM_PROVIDER=openai
   OPENAI_API_KEY=...
   OPENAI_BASE_URL=https://api.openai.com/v1     # or https://api.groq.com/openai/v1, etc.
   OPENAI_MODEL=gpt-4o-mini                      # any chat model your provider offers
   OPENAI_VISION_MODEL=gpt-4o-mini               # must accept images
   CORS_ORIGINS=https://your-frontend.vercel.app
   ```
2. **Frontend**: edit `frontend/config.js` and set `window.STUDY_STUDIO_API` to the backend URL from step 1,
   then import the repo again with **Root Directory** set to `frontend` (no build command needed).

Limits to know about (these come from Vercel, not from the app):
- **Request size:** Vercel functions reject bodies over about 4.5 MB, so each uploaded file must be under that (`MAX_UPLOAD_MB`). Pasted text is not affected by the app, but it travels in the same kind of request body, so extremely large pastes can also hit this platform cap. Splitting a huge book into a few files avoids it.
- **Run time:** `vercel.json` sets `maxDuration` to 60 seconds. Very long texts need many model calls and may need a higher limit (a paid plan) or a backend on a host without short time limits (Render, Railway, Fly.io). The same `backend/` folder runs there with `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.

## Notes on very long text

Short text goes to the model in one call. Longer text is cut into pieces at paragraph/sentence boundaries, each piece is condensed to notes, and the notes are condensed again until they fit in one call; the final summary / Q&A / flashcards is written from those notes. A small local model with a 4k context (phi3:mini) uses small pieces, so a very long text means many calls and takes a while; the progress bar shows where it is. The result then reflects the notes rather than every word, which is the trade-off for supporting any length.
Tune with `SINGLE_PASS_CHARS`, `CHUNK_CHARS`, `MAP_CONCURRENCY`, `OLLAMA_NUM_CTX` (see `.env.example`).

## Tests

```bash
cd backend
pip install -r requirements-dev.txt
pytest                         # API tests with the model mocked
python tests/offline_check.py  # logic checks that need no web framework
```
