(() => {
  "use strict";

  const API = (window.STUDY_STUDIO_API || "").replace(/\/$/, "");
  const $ = (id) => document.getElementById(id);

  const els = {
    status: $("status"), statusText: $("status-text"),
    dropzone: $("dropzone"), fileInput: $("file-input"), fileList: $("file-list"),
    notes: $("notes"), counter: $("counter"), clearNotes: $("clear-notes"),
    modes: document.querySelectorAll(".mode"),
    customWrap: $("custom-wrap"), customPrompt: $("custom-prompt"),
    level: $("level"), count: $("count"), countField: $("count-field"),
    generate: $("generate"),
    resultCard: $("result-card"), resultTitle: $("result-title"),
    progress: $("progress"), progressText: $("progress-text"), barFill: $("bar-fill"),
    error: $("error"), output: $("output"),
    copy: $("copy"), download: $("download"),
  };

  const MODE_LABELS = { summary: "Summary", qa: "Q&A", flashcards: "Flashcards", custom: "Your result" };
  let mode = "summary";
  let controller = null;
  let lastResult = "";

  // ───────────────────────── helpers ─────────────────────────
  function esc(s) {
    return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function inline(s) {
    s = esc(s);
    s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
    s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
    return s;
  }

  // Small, safe Markdown renderer (everything is HTML-escaped first).
  function renderMarkdown(md) {
    const lines = md.replace(/\r/g, "").split("\n");
    let html = "", list = null, para = [];
    const flushPara = () => { if (para.length) { html += "<p>" + inline(para.join(" ")) + "</p>"; para = []; } };
    const closeList = () => { if (list) { html += `</${list}>`; list = null; } };

    const isRow = (l) => /^\s*\|.*\|\s*$/.test(l);
    const isSep = (l) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l);
    const cells = (l) => l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trimEnd();
      let m;
      if (!line.trim()) { flushPara(); closeList(); continue; }
      if (isRow(line) && i + 1 < lines.length && isSep(lines[i + 1])) {
        flushPara(); closeList();
        const head = cells(line);
        let body = "";
        i += 2;
        while (i < lines.length && isRow(lines[i].trimEnd())) {
          body += "<tr>" + cells(lines[i]).map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>";
          i++;
        }
        i--;
        html += `<div class="table-wrap"><table><thead><tr>${head.map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead>` +
                `<tbody>${body}</tbody></table></div>`;
        continue;
      }
      if ((m = line.match(/^(#{1,4})\s+(.*)$/))) {
        flushPara(); closeList();
        const n = Math.min(m[1].length + 1, 5);
        html += `<h${n}>${inline(m[2])}</h${n}>`; continue;
      }
      if ((m = line.match(/^\s*[-*•]\s+(.*)$/))) {
        flushPara();
        if (list !== "ul") { closeList(); html += "<ul>"; list = "ul"; }
        html += `<li>${inline(m[1])}</li>`; continue;
      }
      if ((m = line.match(/^\s*\d+[.)]\s+(.*)$/))) {
        flushPara();
        if (list !== "ol") { closeList(); html += "<ol>"; list = "ol"; }
        html += `<li>${inline(m[1])}</li>`; continue;
      }
      if (/^[-*_]{3,}$/.test(line.trim())) { flushPara(); closeList(); html += "<hr>"; continue; }
      if ((m = line.match(/^\**\s*(Q|A)\s*\d*\s*[:.)]/i))) {
        flushPara(); closeList();
        html += `<p class="${m[1].toUpperCase() === "Q" ? "qa-q" : "qa-a"}">${inline(line.trim())}</p>`; continue;
      }
      closeList();
      para.push(line.trim());
    }
    flushPara(); closeList();
    return html;
  }

  function parseFlashcards(text) {
    const cards = [];
    const clean = (s) => s.replace(/\*\*/g, "").replace(/^\s*[\[“"']+|[\]”"']+\s*$/g, "").trim();
    const re = /Front:\s*([\s\S]*?)\s*Back:\s*([\s\S]*?)(?=\n\s*(?:\d+[.)]\s*)?\**\s*Front:|\s*$)/gi;
    let m;
    while ((m = re.exec(text))) {
      const front = clean(m[1]), back = clean(m[2]);
      if (front && back) cards.push({ front, back });
    }
    return cards;
  }

  function renderFlashcards(text) {
    const cards = parseFlashcards(text);
    if (cards.length < 1) return renderMarkdown(text);
    return (
      `<p class="cards-hint">Click a card to flip it.</p><div class="cards">` +
      cards.map((c) =>
        `<button type="button" class="flip" aria-label="Flashcard, click to flip">` +
        `<div class="flip-inner"><div class="face front"><small>Front</small>${esc(c.front)}</div>` +
        `<div class="face back"><small>Back</small>${esc(c.back)}</div></div></button>`
      ).join("") + `</div>`
    );
  }

  function updateCounter() {
    const t = els.notes.value;
    const words = (t.trim().match(/\S+/g) || []).length;
    els.counter.textContent = `${words.toLocaleString()} words · ${t.length.toLocaleString()} characters`;
    try { localStorage.setItem("ss-notes", t); } catch (_) { /* storage can be unavailable */ }
  }

  // ───────────────────────── server status ─────────────────────────
  async function checkHealth() {
    const set = (cls, text) => { els.status.className = "status " + cls; els.statusText.textContent = text; };
    try {
      const r = await fetch(API + "/api/health");
      const h = await r.json();
      if (h.provider === "ollama") {
        if (!h.reachable) return set("bad", "Ollama isn't running");
        if (h.text_model_installed === false) return set("warn", `Run: ollama pull ${h.model}`);
        return set("ok", `Ready · ${h.model}`);
      }
      return h.reachable ? set("ok", `Ready · ${h.model}`) : set("bad", "API key missing on server");
    } catch (_) {
      set("bad", "Can't reach the server");
    }
  }

  // ───────────────────────── file uploads ─────────────────────────
  async function handleFiles(fileList) {
    for (const file of Array.from(fileList)) {
      const li = document.createElement("li");
      li.innerHTML = `<span class="spin"></span><span class="name"></span><span class="state">Reading…</span>` +
        `<button type="button" class="remove" aria-label="Remove" hidden>×</button>`;
      li.querySelector(".name").textContent = file.name;
      li.querySelector(".remove").addEventListener("click", () => li.remove());
      els.fileList.appendChild(li);
      await uploadOne(file, li);
    }
  }

  async function uploadOne(file, li) {
    const state = li.querySelector(".state");
    const finish = (cls, msg) => {
      li.classList.add(cls);
      const spin = li.querySelector(".spin");
      if (spin) spin.remove();
      state.textContent = msg;
      li.querySelector(".remove").hidden = false;
    };
    try {
      const fd = new FormData();
      fd.append("files", file);
      const r = await fetch(API + "/api/extract", { method: "POST", body: fd });
      if (!r.ok) throw new Error(r.status === 413 ? "File too large for the server" : `Server error ${r.status}`);
      const data = await r.json();
      const res = data.files && data.files[0];
      if (!res || res.error) return finish("fail", (res && res.error) || "Could not read file");
      const sep = els.notes.value.trim() ? "\n\n" : "";
      els.notes.value = `${els.notes.value.replace(/\s+$/, "")}${sep}--- ${file.name} ---\n${res.text}\n`;
      updateCounter();
      finish("done", `Added ${res.chars.toLocaleString()} characters`);
    } catch (e) {
      finish("fail", e.message || "Upload failed");
    }
  }

  ["dragenter", "dragover"].forEach((ev) =>
    els.dropzone.addEventListener(ev, (e) => { e.preventDefault(); els.dropzone.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) =>
    els.dropzone.addEventListener(ev, (e) => { e.preventDefault(); els.dropzone.classList.remove("drag"); }));
  els.dropzone.addEventListener("drop", (e) => { if (e.dataTransfer.files.length) handleFiles(e.dataTransfer.files); });
  els.fileInput.addEventListener("change", () => { handleFiles(els.fileInput.files); els.fileInput.value = ""; });

  // ───────────────────────── controls ─────────────────────────
  els.notes.addEventListener("input", updateCounter);
  els.clearNotes.addEventListener("click", () => {
    if (!els.notes.value || confirm("Clear all the text in the box?")) { els.notes.value = ""; els.fileList.innerHTML = ""; updateCounter(); }
  });

  els.modes.forEach((btn) => btn.addEventListener("click", () => {
    mode = btn.dataset.mode;
    els.modes.forEach((b) => { const on = b === btn; b.classList.toggle("active", on); b.setAttribute("aria-selected", on); });
    els.customWrap.hidden = mode !== "custom";
    els.countField.hidden = mode === "summary" || mode === "custom";
  }));
  els.countField.hidden = true;

  // ───────────────────────── generation ─────────────────────────
  function showError(msg) { els.error.textContent = msg; els.error.hidden = false; }

  function setBusy(busy) {
    els.generate.textContent = busy ? "Stop" : "Generate";
    els.generate.classList.toggle("stop", busy);
    els.progress.hidden = !busy;
    document.querySelector(".bar").classList.toggle("indeterminate", busy);
  }

  function handleEvent(ev) {
    if (ev.type === "progress") {
      els.progressText.textContent = ev.message;
      const bar = document.querySelector(".bar");
      if (ev.total) {
        bar.classList.remove("indeterminate");
        els.barFill.style.width = Math.max(8, Math.round((ev.done / ev.total) * 100)) + "%";
      } else {
        bar.classList.add("indeterminate");
      }
    } else if (ev.type === "result") {
      lastResult = ev.content;
      els.output.innerHTML = mode === "flashcards" ? renderFlashcards(ev.content) : renderMarkdown(ev.content);
      if (ev.condensed) {
        els.output.insertAdjacentHTML("beforeend",
          `<p class="note">Your text was long, so it was condensed into notes first and this result is based on those notes.</p>`);
      }
      els.output.querySelectorAll(".flip").forEach((b) => b.addEventListener("click", () => b.classList.toggle("flipped")));
    } else if (ev.type === "error") {
      showError(ev.message);
    }
  }

  async function generate() {
    if (controller) { controller.abort(); return; }

    const text = els.notes.value;
    const prompt = els.customPrompt.value;
    els.error.hidden = true;
    if (mode === "custom" && !prompt.trim()) { els.resultCard.hidden = false; return showError("Tell me what you would like to generate."); }
    if (mode !== "custom" && !text.trim()) { els.resultCard.hidden = false; return showError("Add some study content first: upload a file or type in the box."); }

    const body = {
      text, mode, prompt,
      level: els.level.value,
      count: els.count.value ? parseInt(els.count.value, 10) : null,
    };

    controller = new AbortController();
    lastResult = "";
    els.output.innerHTML = "";
    els.resultTitle.textContent = MODE_LABELS[mode];
    els.resultCard.hidden = false;
    els.barFill.style.width = "8%";
    els.progressText.textContent = "Starting…";
    setBusy(true);
    els.resultCard.scrollIntoView({ behavior: "smooth", block: "nearest" });

    try {
      const res = await fetch(API + "/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(typeof err.detail === "string" ? err.detail : `Server error ${res.status}`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf("\n")) >= 0) {
          const line = buf.slice(0, i).trim();
          buf = buf.slice(i + 1);
          if (line) handleEvent(JSON.parse(line));
        }
      }
      if (buf.trim()) handleEvent(JSON.parse(buf));
    } catch (e) {
      if (e.name === "AbortError") showError("Stopped.");
      else showError(e.message || "Could not reach the server.");
    } finally {
      controller = null;
      setBusy(false);
    }
  }
  els.generate.addEventListener("click", generate);

  // ───────────────────────── copy / download ─────────────────────────
  els.copy.addEventListener("click", async () => {
    if (!lastResult) return;
    try { await navigator.clipboard.writeText(lastResult); els.copy.textContent = "Copied"; }
    catch (_) { els.copy.textContent = "Copy failed"; }
    setTimeout(() => (els.copy.textContent = "Copy"), 1500);
  });

  els.download.addEventListener("click", () => {
    if (!lastResult) return;
    const url = URL.createObjectURL(new Blob([lastResult], { type: "text/markdown" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: `study-${mode}.md` });
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  });

  // ───────────────────────── init ─────────────────────────
  try { els.notes.value = localStorage.getItem("ss-notes") || ""; } catch (_) { /* ignore */ }
  updateCounter();
  checkHealth();
})();