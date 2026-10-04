/**
 * ORVIA — Investigation Workspace JavaScript (Phase 8)
 * Vanilla JS, no external dependencies, no LLMs, fully local.
 */

"use strict";

// ─── Helpers ─────────────────────────────────────────────────────────────────

/**
 * Show a flash message inside a container element.
 * Auto-removes after 5 seconds.
 */
function showFlash(container, message, type = "error") {
  const el = document.createElement("div");
  el.className = `inv-flash-message ${type}`;
  el.textContent = message;
  container.prepend(el);
  setTimeout(() => { if (el.parentNode) el.remove(); }, 5000);
}

/**
 * Generic API call helper using fetch.
 */
async function apiCall(url, method = "GET", body = null) {
  const opts = {
    method,
    headers: { "Content-Type": "application/json", "Accept": "application/json" },
  };
  if (body !== null && method !== "GET") {
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  const data = await res.json();
  if (!res.ok || data.status === "error") {
    throw new Error(data.error || `HTTP ${res.status}`);
  }
  return data;
}

/** Get the investigation ID from the page meta tag or data attribute. */
function getInvId() {
  const el = document.querySelector("[data-inv-id]");
  return el ? el.getAttribute("data-inv-id") : null;
}

// ─── Tab Switching ────────────────────────────────────────────────────────────

function initInvestigationTabs() {
  const tabs = document.querySelectorAll(".inv-nav-tab[data-tab]");
  if (!tabs.length) return;

  // Activate tab by name
  function activateTab(name) {
    document.querySelectorAll(".inv-nav-tab").forEach(t => {
      t.classList.toggle("active", t.getAttribute("data-tab") === name);
    });
    document.querySelectorAll(".inv-tab-panel").forEach(p => {
      p.classList.toggle("active", p.getAttribute("data-tab") === name);
    });
  }

  // Resolve initial tab from URL ?tab= param
  const params = new URLSearchParams(window.location.search);
  const initialTab = params.get("tab") || (tabs[0] && tabs[0].getAttribute("data-tab")) || "overview";
  activateTab(initialTab);

  tabs.forEach(tab => {
    tab.addEventListener("click", (e) => {
      e.preventDefault();
      const name = tab.getAttribute("data-tab");
      activateTab(name);
      // Update URL without reload
      const url = new URL(window.location.href);
      url.searchParams.set("tab", name);
      history.replaceState({}, "", url.toString());
    });
  });
}

// ─── Status Controls ──────────────────────────────────────────────────────────

function initStatusControls() {
  const invId = getInvId();
  if (!invId) return;

  document.querySelectorAll("[data-status-action]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const newStatus = btn.getAttribute("data-status-action");
      const flash = document.getElementById("inv-global-flash");
      try {
        btn.disabled = true;
        btn.textContent = "…";
        const res = await apiCall(`/api/investigations/${invId}/status`, "POST", { status: newStatus });
        if (res.warning) {
          if (!confirm(`Warning: ${res.warning}\n\nContinue?`)) {
            btn.disabled = false;
            btn.textContent = newStatus.charAt(0).toUpperCase() + newStatus.slice(1);
            return;
          }
        }
        window.location.reload();
      } catch (err) {
        btn.disabled = false;
        btn.textContent = btn.getAttribute("data-original-text") || newStatus;
        if (flash) showFlash(flash.parentElement, err.message, "error");
      }
    });
  });
}

// ─── Toggle Inline Forms ──────────────────────────────────────────────────────

function initQuickForms() {
  const invId = getInvId();
  if (!invId) return;

  // Toggle form visibility
  document.querySelectorAll("[data-toggle-form]").forEach(btn => {
    btn.addEventListener("click", () => {
      const targetId = btn.getAttribute("data-toggle-form");
      const form = document.getElementById(targetId);
      if (form) form.classList.toggle("hidden");
    });
  });

  // ── Evidence form ──
  const evidenceForm = document.getElementById("form-add-evidence");
  if (evidenceForm) {
    evidenceForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const data = {
        statement: evidenceForm.querySelector("[name=statement]")?.value?.trim(),
        source_id: evidenceForm.querySelector("[name=source_id]")?.value,
        excerpt: evidenceForm.querySelector("[name=excerpt]")?.value?.trim() || "",
        location: evidenceForm.querySelector("[name=location]")?.value?.trim() || "",
        evidence_type: evidenceForm.querySelector("[name=evidence_type]")?.value || "OBSERVATION",
        confidence: parseFloat(evidenceForm.querySelector("[name=confidence]")?.value || "1.0"),
      };
      if (!data.statement || !data.source_id) {
        showFlash(evidenceForm, "Statement and source are required.", "error"); return;
      }
      try {
        await apiCall(`/api/investigations/${invId}/evidence`, "POST", data);
        window.location.reload();
      } catch (err) {
        showFlash(evidenceForm, err.message, "error");
      }
    });
  }

  // ── Question form ──
  const questionForm = document.getElementById("form-add-question");
  if (questionForm) {
    questionForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const question = questionForm.querySelector("[name=question]")?.value?.trim();
      if (!question) { showFlash(questionForm, "Question text is required.", "error"); return; }
      try {
        await apiCall(`/api/investigations/${invId}/questions`, "POST", { question });
        window.location.reload();
      } catch (err) {
        showFlash(questionForm, err.message, "error");
      }
    });
  }

  // ── Finding form ──
  const findingForm = document.getElementById("form-add-finding");
  if (findingForm) {
    findingForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const data = {
        title: findingForm.querySelector("[name=title]")?.value?.trim(),
        statement: findingForm.querySelector("[name=statement]")?.value?.trim(),
        status: findingForm.querySelector("[name=status]")?.value || "DRAFT",
      };
      if (!data.title || !data.statement) {
        showFlash(findingForm, "Title and statement are required.", "error"); return;
      }
      try {
        await apiCall(`/api/investigations/${invId}/findings`, "POST", data);
        window.location.reload();
      } catch (err) {
        showFlash(findingForm, err.message, "error");
      }
    });
  }

  // ── Note form ──
  const noteForm = document.getElementById("form-add-note");
  if (noteForm) {
    noteForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const data = {
        title: noteForm.querySelector("[name=title]")?.value?.trim() || "",
        content: noteForm.querySelector("[name=content]")?.value?.trim(),
        note_type: noteForm.querySelector("[name=note_type]")?.value || "GENERAL",
      };
      if (!data.content) { showFlash(noteForm, "Note content is required.", "error"); return; }
      try {
        await apiCall(`/api/investigations/${invId}/notes`, "POST", data);
        window.location.reload();
      } catch (err) {
        showFlash(noteForm, err.message, "error");
      }
    });
  }
}

// ─── Attachment Controls ──────────────────────────────────────────────────────

function initAttachmentControls() {
  const invId = getInvId();
  if (!invId) return;

  // Source attachment
  const attachSourceBtn = document.getElementById("btn-attach-source");
  if (attachSourceBtn) {
    attachSourceBtn.addEventListener("click", async () => {
      const select = document.getElementById("sel-source");
      const relType = document.getElementById("sel-source-rel")?.value || "RELEVANT";
      const sourceId = select?.value;
      if (!sourceId) { alert("Please select a source."); return; }
      try {
        attachSourceBtn.disabled = true;
        await apiCall(`/api/investigations/${invId}/sources`, "POST", { source_id: sourceId, relationship_type: relType });
        window.location.reload();
      } catch (err) {
        attachSourceBtn.disabled = false;
        alert("Error: " + err.message);
      }
    });
  }

  // Concept tracking
  const trackConceptBtn = document.getElementById("btn-track-concept");
  if (trackConceptBtn) {
    trackConceptBtn.addEventListener("click", async () => {
      const select = document.getElementById("sel-concept");
      const role = document.getElementById("sel-concept-role")?.value || "KEY_CONCEPT";
      const conceptId = select?.value;
      if (!conceptId) { alert("Please select a concept."); return; }
      try {
        trackConceptBtn.disabled = true;
        await apiCall(`/api/investigations/${invId}/concepts`, "POST", { concept_id: conceptId, role });
        window.location.reload();
      } catch (err) {
        trackConceptBtn.disabled = false;
        alert("Error: " + err.message);
      }
    });
  }
}

// ─── Evidence Filter ──────────────────────────────────────────────────────────

function initEvidenceFilter() {
  const filterBtns = document.querySelectorAll(".evidence-filter-btn[data-ev-type]");
  if (!filterBtns.length) return;

  filterBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      filterBtns.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const type = btn.getAttribute("data-ev-type");
      document.querySelectorAll(".research-record-evidence").forEach(card => {
        if (type === "ALL") {
          card.style.display = "";
        } else {
          const cardType = card.getAttribute("data-ev-type") || "";
          card.style.display = cardType === type ? "" : "none";
        }
      });
    });
  });
}

// ─── Delete Controls ──────────────────────────────────────────────────────────

function initDeleteControls() {
  const invId = getInvId();
  if (!invId) return;

  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-delete]");
    if (!btn) return;
    const endpoint = btn.getAttribute("data-delete");
    const label = btn.getAttribute("data-delete-label") || "this item";
    if (!confirm(`Delete ${label}? This cannot be undone.`)) return;
    try {
      btn.disabled = true;
      await apiCall(endpoint, "POST");
      const row = btn.closest(".research-record, .inv-source-row, .concept-chip-row, .activity-item");
      if (row) row.remove();
      else window.location.reload();
    } catch (err) {
      btn.disabled = false;
      alert("Error: " + err.message);
    }
  });
}

// ─── Question Status Controls ─────────────────────────────────────────────────

function initQuestionControls() {
  const invId = getInvId();
  if (!invId) return;

  document.querySelectorAll("[data-question-status]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const qId = btn.getAttribute("data-question-id");
      const status = btn.getAttribute("data-question-status");
      let resolution_note = null;
      if (status === "RESOLVED") {
        resolution_note = prompt("Resolution note (optional):");
        if (resolution_note === null) return; // cancelled
      }
      try {
        btn.disabled = true;
        await apiCall(`/api/investigations/${invId}/questions/${qId}/status`, "POST", { status, resolution_note });
        window.location.reload();
      } catch (err) {
        btn.disabled = false;
        alert("Error: " + err.message);
      }
    });
  });
}

// ─── Client-side Record Search ────────────────────────────────────────────────

function initInvestigationSearch() {
  const searchInput = document.getElementById("inv-record-search");
  if (!searchInput) return;

  searchInput.addEventListener("input", () => {
    const query = searchInput.value.toLowerCase().trim();
    document.querySelectorAll(".research-record").forEach(card => {
      const text = (card.textContent || "").toLowerCase();
      card.style.display = !query || text.includes(query) ? "" : "none";
    });
  });
}

// ─── New Investigation Form Page ──────────────────────────────────────────────

function initNewInvestigationForm() {
  const form = document.getElementById("form-new-investigation");
  if (!form) return;

  // Enter in title focuses question
  const titleInput = form.querySelector("[name=title]");
  const questionArea = form.querySelector("[name=research_question]");
  if (titleInput && questionArea) {
    titleInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); questionArea.focus(); }
    });
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const submitBtn = form.querySelector("[type=submit]");
    const data = {
      title: form.querySelector("[name=title]")?.value?.trim(),
      research_question: form.querySelector("[name=research_question]")?.value?.trim(),
      description: form.querySelector("[name=description]")?.value?.trim() || "",
      status: form.querySelector("[name=status]")?.value || "active",
    };
    if (!data.title || !data.research_question) {
      showFlash(form, "Title and research question are required.", "error"); return;
    }
    try {
      if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = "Creating…"; }
      const res = await apiCall("/api/investigations", "POST", data);
      const invId = res.investigation?.id;
      if (invId) {
        window.location.href = `/investigations/${invId}`;
      } else {
        window.location.href = "/investigations";
      }
    } catch (err) {
      if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = "Start Investigation →"; }
      showFlash(form, err.message, "error");
    }
  });
}

// ─── Bootstrap ────────────────────────────────────────────────────────────────

function initAll() {
  initInvestigationTabs();
  initStatusControls();
  initQuickForms();
  initAttachmentControls();
  initEvidenceFilter();
  initDeleteControls();
  initQuestionControls();
  initInvestigationSearch();
  initNewInvestigationForm();
}

document.addEventListener("DOMContentLoaded", initAll);
