/**
 * ORVIA Explore — Capture Research Interface Controller
 *
 * Handles four capture workflows:
 *   A. Upload Files      → POST /api/sources/import  (multipart)
 *   B. Paste Content     → POST /api/sources/paste   (JSON)
 *   C. Create Note       → POST /api/sources/paste   (JSON)
 *   D. Import Folder     → POST /api/sources/import  (multipart, per file)
 *
 * No external dependencies. Reuses existing ORVIA ingestion pipeline.
 */
(function () {
  'use strict';

  // ── Constants ──────────────────────────────────────────────────────────────
  const VALID_EXTS    = ['.txt', '.text', '.csv', '.json'];
  const MAX_FILE_SIZE = 25 * 1024 * 1024; // 25 MB

  // ── Root element guard (only run on Explore page) ──────────────────────────
  const overlay = document.getElementById('cr-overlay');
  if (!overlay) return;

  // ── Open / Close ───────────────────────────────────────────────────────────
  function openCapture() {
    overlay.classList.add('open');
    document.body.style.overflow = 'hidden';
    const openBtn = document.getElementById('cr-open-btn');
    if (openBtn) openBtn.setAttribute('aria-expanded', 'true');
    // Focus first method tab for keyboard users
    const firstTab = overlay.querySelector('.cr-method-tab');
    if (firstTab) setTimeout(() => firstTab.focus(), 60);
  }

  function closeCapture() {
    overlay.classList.remove('open');
    document.body.style.overflow = '';
    const openBtn = document.getElementById('cr-open-btn');
    if (openBtn) openBtn.setAttribute('aria-expanded', 'false');
  }

  const openBtn      = document.getElementById('cr-open-btn');
  const openEmptyBtn = document.getElementById('cr-open-empty-btn');
  const closeBtn     = document.getElementById('cr-close-btn');

  if (openBtn)      openBtn.addEventListener('click', openCapture);
  if (openEmptyBtn) openEmptyBtn.addEventListener('click', openCapture);
  if (closeBtn)     closeBtn.addEventListener('click', closeCapture);

  // Backdrop click
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) closeCapture();
  });

  // Escape key (orvia.js also handles .modal-overlay.open, this is a belt-and-suspenders)
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && overlay.classList.contains('open')) {
      closeCapture();
    }
  });

  // ── Method Tab Switching ───────────────────────────────────────────────────
  const methodTabs = overlay.querySelectorAll('.cr-method-tab');
  const panels     = overlay.querySelectorAll('.cr-panel');

  methodTabs.forEach(tab => {
    tab.addEventListener('click', () => switchMethod(tab.dataset.method));
    tab.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        switchMethod(tab.dataset.method);
      }
    });
  });

  function switchMethod(method) {
    methodTabs.forEach(t => {
      const active = t.dataset.method === method;
      t.classList.toggle('active', active);
      t.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    panels.forEach(p => {
      const active = p.id === `cr-panel-${method}`;
      p.style.display = active ? '' : 'none';
      p.classList.toggle('active', active);
    });
  }

  // ── Shared Helpers ─────────────────────────────────────────────────────────
  function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  }

  function isValidExt(filename) {
    const ext = '.' + filename.split('.').pop().toLowerCase();
    return VALID_EXTS.includes(ext);
  }

  function countWords(text) {
    return text.trim().split(/\s+/).filter(Boolean).length;
  }

  function show(el) { if (el) el.style.display = ''; }
  function hide(el) { if (el) el.style.display = 'none'; }
  function setText(el, val) { if (el) el.textContent = String(val); }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  /**
   * After a successful import, lightly update the Explore page source count
   * and, if the page was showing the empty state, reload to show the library.
   */
  function updateExploreCounts(addedCount) {
    if (addedCount <= 0) return;

    // Update "All Sources (N)" chip
    const chip = document.querySelector('.explore-workspace .btn.btn-primary');
    if (chip) {
      const m = chip.textContent.match(/(\d+)/);
      if (m) chip.textContent = `All Sources (${parseInt(m[1], 10) + addedCount})`;
    }

    // If empty-state is showing, fade it then reload
    const emptyEl = document.querySelector('.explore-workspace .empty-state');
    if (emptyEl) {
      emptyEl.style.transition = 'opacity 0.6s ease';
      emptyEl.style.opacity = '0.4';
      setTimeout(() => { window.location.reload(); }, 1400);
    }
  }

  // ══════════════════════════════════════════════════════════════════════════
  // A. UPLOAD FILES
  // ══════════════════════════════════════════════════════════════════════════
  (function initUpload() {
    const dropzone        = document.getElementById('cr-dropzone');
    const fileInput       = document.getElementById('cr-file-input');
    const fileInputExtra  = document.getElementById('cr-file-input-extra');
    const addMoreBtn      = document.getElementById('cr-add-more-btn');
    const fileList        = document.getElementById('cr-file-list');
    const fileCountLabel  = document.getElementById('cr-file-count-label');
    const fileEntries     = document.getElementById('cr-file-entries');
    const countDetected   = document.getElementById('cr-count-detected');
    const countSupported  = document.getElementById('cr-count-supported');
    const countUnsupported = document.getElementById('cr-count-unsupported');
    const verifySummary   = document.getElementById('cr-verify-summary');
    const progressWrap    = document.getElementById('cr-upload-progress');
    const progressEntries = document.getElementById('cr-progress-entries');
    const errorBox        = document.getElementById('cr-upload-error');
    const errorMsg        = document.getElementById('cr-upload-error-msg');
    const successState    = document.getElementById('cr-upload-success');
    const successStats    = document.getElementById('cr-upload-success-stats');
    const footer          = document.getElementById('cr-upload-footer');
    const importBtn       = document.getElementById('cr-upload-import-btn');
    const continueBtn     = document.getElementById('cr-upload-continue-btn');

    let pendingFiles = [];

    function updateFileList() {
      if (pendingFiles.length === 0) {
        show(dropzone);
        hide(fileList);
        hide(verifySummary);
        if (importBtn) importBtn.disabled = true;
        return;
      }

      hide(dropzone);
      show(fileList);

      const supported   = pendingFiles.filter(f => isValidExt(f.name) && f.size <= MAX_FILE_SIZE);
      const unsupported = pendingFiles.filter(f => !isValidExt(f.name));

      setText(fileCountLabel, `${pendingFiles.length} file${pendingFiles.length !== 1 ? 's' : ''} selected`);
      setText(countDetected,   pendingFiles.length);
      setText(countSupported,  supported.length);
      setText(countUnsupported, unsupported.length);

      if (verifySummary) {
        if (pendingFiles.length > 1) show(verifySummary); else hide(verifySummary);
      }

      if (fileEntries) {
        fileEntries.innerHTML = '';
        pendingFiles.forEach((file, idx) => {
          const valid  = isValidExt(file.name);
          const tooBig = file.size > MAX_FILE_SIZE;
          let status = 'Ready', statusClass = 'ok';
          if (!valid)  { status = 'Unsupported format';     statusClass = 'warn'; }
          else if (tooBig) { status = 'Too large (max 25 MB)'; statusClass = 'err'; }

          const ext   = file.name.split('.').pop().toUpperCase();
          const entry = document.createElement('div');
          entry.className = 'cr-file-entry';
          entry.innerHTML = `
            <span class="badge badge-default" style="font-size:0.6rem;">${ext}</span>
            <div style="min-width:0;">
              <div class="cr-file-name">${escapeHtml(file.name)}</div>
              <div class="cr-file-meta">${formatBytes(file.size)}</div>
            </div>
            <span class="cr-file-status ${statusClass}">${status}</span>
            <button class="cr-file-remove-btn" data-idx="${idx}" type="button"
                    aria-label="Remove ${escapeHtml(file.name)}">✕</button>`;
          fileEntries.appendChild(entry);
        });

        fileEntries.querySelectorAll('.cr-file-remove-btn').forEach(btn => {
          btn.addEventListener('click', () => {
            pendingFiles.splice(parseInt(btn.dataset.idx, 10), 1);
            hide(errorBox);
            updateFileList();
          });
        });
      }

      const hasReady = pendingFiles.some(f => isValidExt(f.name) && f.size <= MAX_FILE_SIZE);
      if (importBtn) importBtn.disabled = !hasReady;
    }

    function addFiles(fileCollection) {
      Array.from(fileCollection).forEach(f => {
        const exists = pendingFiles.some(p => p.name === f.name && p.size === f.size);
        if (!exists) pendingFiles.push(f);
      });
      hide(errorBox);
      updateFileList();
    }

    // Dropzone events
    if (dropzone) {
      dropzone.addEventListener('click', () => { if (fileInput) fileInput.click(); });
      dropzone.addEventListener('dragover',  (e) => { e.preventDefault(); dropzone.classList.add('dragover'); });
      dropzone.addEventListener('dragleave', ()  => dropzone.classList.remove('dragover'));
      dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
        if (e.dataTransfer && e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
      });
    }

    if (fileInput)      fileInput.addEventListener('change',      () => { if (fileInput.files.length) addFiles(fileInput.files); fileInput.value = ''; });
    if (fileInputExtra) fileInputExtra.addEventListener('change', () => { if (fileInputExtra.files.length) addFiles(fileInputExtra.files); fileInputExtra.value = ''; });
    if (addMoreBtn)     addMoreBtn.addEventListener('click', () => { if (fileInputExtra) fileInputExtra.click(); });

    // Import pipeline
    async function executeUpload() {
      const validFiles = pendingFiles.filter(f => isValidExt(f.name) && f.size <= MAX_FILE_SIZE);
      if (!validFiles.length) return;

      hide(fileList);
      hide(errorBox);
      hide(footer);
      show(progressWrap);

      if (progressEntries) {
        progressEntries.innerHTML = '';
        validFiles.forEach(f => {
          const el = document.createElement('div');
          el.className = 'cr-progress-entry pending';
          el.dataset.fname = f.name;
          el.innerHTML = `<span class="cr-progress-dot"></span>
            <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(f.name)}</span>
            <span class="cr-file-meta" style="margin-left:var(--sp-3);flex-shrink:0;"></span>`;
          progressEntries.appendChild(el);
        });
      }

      let added = 0, skipped = 0, failed = 0;

      for (const file of validFiles) {
        const entryEl  = progressEntries ? progressEntries.querySelector(`[data-fname="${CSS.escape(file.name)}"]`) : null;
        const metaSpan = entryEl ? entryEl.querySelector('.cr-file-meta') : null;

        if (entryEl) { entryEl.className = 'cr-progress-entry active'; }
        if (metaSpan) metaSpan.textContent = 'Processing…';

        const fd = new FormData();
        fd.append('file', file);

        try {
          const resp = await fetch('/api/sources/import', { method: 'POST', body: fd });
          const data = await resp.json();

          if (resp.ok && data.status === 'ok') {
            added++;
            if (entryEl) entryEl.className = 'cr-progress-entry done';
            if (metaSpan) metaSpan.textContent = 'Added';
          } else if (resp.status === 409 && data.status === 'duplicate') {
            skipped++;
            if (entryEl) entryEl.className = 'cr-progress-entry dupe';
            if (metaSpan) metaSpan.textContent = 'Duplicate — skipped';
          } else {
            failed++;
            if (entryEl) entryEl.className = 'cr-progress-entry error';
            if (metaSpan) metaSpan.textContent = data.error || 'Failed';
          }
        } catch {
          failed++;
          if (entryEl) entryEl.className = 'cr-progress-entry error';
          if (metaSpan) metaSpan.textContent = 'Network error';
        }
      }

      await new Promise(r => setTimeout(r, 320));
      hide(progressWrap);
      show(successState);

      const parts = [];
      if (added)   parts.push(`<strong>${added} source${added !== 1 ? 's' : ''} added</strong>`);
      if (skipped) parts.push(`${skipped} duplicate${skipped !== 1 ? 's' : ''} skipped`);
      if (failed)  parts.push(`${failed} failed`);
      if (successStats) successStats.innerHTML = parts.join(' &nbsp;·&nbsp; ');

      updateExploreCounts(added);
    }

    if (importBtn) importBtn.addEventListener('click', executeUpload);

    if (continueBtn) {
      continueBtn.addEventListener('click', () => {
        closeCapture();
        resetUpload();
      });
    }

    function resetUpload() {
      pendingFiles = [];
      hide(progressWrap);
      hide(successState);
      hide(errorBox);
      hide(fileList);
      hide(verifySummary);
      show(dropzone);
      show(footer);
      if (importBtn) importBtn.disabled = true;
    }

    // Reset on overlay close (so state is fresh next open)
    overlay.addEventListener('click', (e) => { if (e.target === overlay) resetUpload(); });
    if (closeBtn) closeBtn.addEventListener('click', resetUpload);
  })();

  // ══════════════════════════════════════════════════════════════════════════
  // B. PASTE CONTENT
  // ══════════════════════════════════════════════════════════════════════════
  (function initPaste() {
    const titleInput    = document.getElementById('cr-paste-title');
    const contentArea   = document.getElementById('cr-paste-content');
    const wordsEl       = document.getElementById('cr-paste-words');
    const charsEl       = document.getElementById('cr-paste-chars');
    const saveBtn       = document.getElementById('cr-paste-save-btn');
    const resetBtn      = document.getElementById('cr-paste-reset-btn');
    const errorBox      = document.getElementById('cr-paste-error');
    const errorMsg      = document.getElementById('cr-paste-error-msg');
    const dupBox        = document.getElementById('cr-paste-duplicate');
    const dupMsg        = document.getElementById('cr-paste-duplicate-msg');
    const viewExisting  = document.getElementById('cr-paste-view-existing-btn');
    const forceBtn      = document.getElementById('cr-paste-force-btn');
    const successState  = document.getElementById('cr-paste-success');
    const successStats  = document.getElementById('cr-paste-success-stats');
    const viewBtn       = document.getElementById('cr-paste-view-btn');
    const anotherBtn    = document.getElementById('cr-paste-another-btn');
    const footer        = document.getElementById('cr-paste-footer');

    // Live count
    if (contentArea) {
      contentArea.addEventListener('input', () => {
        const t = contentArea.value;
        setText(wordsEl, countWords(t).toLocaleString());
        setText(charsEl, t.length.toLocaleString());
      });
    }

    async function executePaste(force) {
      const title   = titleInput   ? titleInput.value.trim()   : '';
      const content = contentArea  ? contentArea.value.trim()  : '';

      hide(errorBox); hide(dupBox);

      if (!title)   { show(errorBox); setText(errorMsg, 'Please enter a source title.'); if (titleInput) titleInput.focus(); return; }
      if (!content) { show(errorBox); setText(errorMsg, 'Content cannot be empty.'); if (contentArea) contentArea.focus(); return; }

      if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Saving…'; }

      try {
        const resp = await fetch('/api/sources/paste', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title, content, source_type: 'paste', force }),
        });
        const data = await resp.json();

        if (resp.ok && data.status === 'ok') {
          hide(footer);
          show(successState);
          const wc = data.word_count      ? `${Number(data.word_count).toLocaleString()} words`           : '';
          const cc = data.character_count ? `${Number(data.character_count).toLocaleString()} characters` : '';
          const nc = data.concepts_found  ? `${data.concepts_found} concepts extracted`                    : '';
          if (successStats) successStats.textContent = [wc, cc, nc].filter(Boolean).join(' · ');
          if (viewBtn && data.source_id) viewBtn.href = `/sources/${data.source_id}`;
          updateExploreCounts(1);
        } else if (resp.status === 409 && data.status === 'duplicate') {
          show(dupBox);
          setText(dupMsg, data.error || 'An existing source appears to contain the same material.');
          if (viewExisting && data.duplicate_id) viewExisting.href = `/sources/${data.duplicate_id}`;
        } else {
          show(errorBox);
          setText(errorMsg, data.error || 'Failed to save source.');
        }
      } catch {
        show(errorBox);
        setText(errorMsg, 'Network error while saving source.');
      } finally {
        if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Save as Source'; }
      }
    }

    if (saveBtn)    saveBtn.addEventListener('click',  () => executePaste(false));
    if (forceBtn)   forceBtn.addEventListener('click', () => { hide(dupBox); executePaste(true); });
    if (anotherBtn) anotherBtn.addEventListener('click', resetPaste);
    if (resetBtn)   resetBtn.addEventListener('click',   resetPaste);

    function resetPaste() {
      if (titleInput)  titleInput.value  = '';
      if (contentArea) contentArea.value = '';
      setText(wordsEl, '0'); setText(charsEl, '0');
      hide(errorBox); hide(dupBox); hide(successState);
      show(footer);
    }
  })();

  // ══════════════════════════════════════════════════════════════════════════
  // C. CREATE RESEARCH NOTE
  // ══════════════════════════════════════════════════════════════════════════
  (function initNote() {
    const titleInput    = document.getElementById('cr-note-title');
    const contentArea   = document.getElementById('cr-note-content');
    const wordsEl       = document.getElementById('cr-note-words');
    const charsEl       = document.getElementById('cr-note-chars');
    const saveBtn       = document.getElementById('cr-note-save-btn');
    const resetBtn      = document.getElementById('cr-note-reset-btn');
    const errorBox      = document.getElementById('cr-note-error');
    const errorMsg      = document.getElementById('cr-note-error-msg');
    const dupBox        = document.getElementById('cr-note-duplicate');
    const dupMsg        = document.getElementById('cr-note-duplicate-msg');
    const viewExisting  = document.getElementById('cr-note-view-existing-btn');
    const forceBtn      = document.getElementById('cr-note-force-btn');
    const successState  = document.getElementById('cr-note-success');
    const successStats  = document.getElementById('cr-note-success-stats');
    const viewBtn       = document.getElementById('cr-note-view-btn');
    const anotherBtn    = document.getElementById('cr-note-another-btn');
    const footer        = document.getElementById('cr-note-footer');

    if (contentArea) {
      contentArea.addEventListener('input', () => {
        const t = contentArea.value;
        setText(wordsEl, countWords(t).toLocaleString());
        setText(charsEl, t.length.toLocaleString());
      });
    }

    async function executeNote(force) {
      const title   = titleInput   ? titleInput.value.trim()   : '';
      const content = contentArea  ? contentArea.value.trim()  : '';

      hide(errorBox); hide(dupBox);

      if (!title)   { show(errorBox); setText(errorMsg, 'Please enter a note title.'); if (titleInput) titleInput.focus(); return; }
      if (!content) { show(errorBox); setText(errorMsg, 'Note content cannot be empty.'); if (contentArea) contentArea.focus(); return; }

      if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Saving…'; }

      try {
        const resp = await fetch('/api/sources/paste', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title, content, source_type: 'note', force }),
        });
        const data = await resp.json();

        if (resp.ok && data.status === 'ok') {
          hide(footer);
          show(successState);
          const wc = data.word_count ? `${Number(data.word_count).toLocaleString()} words` : '';
          const nc = data.concepts_found ? `${data.concepts_found} concepts extracted` : '';
          if (successStats) successStats.textContent = [wc, nc].filter(Boolean).join(' · ');
          if (viewBtn && data.source_id) viewBtn.href = `/sources/${data.source_id}`;
          updateExploreCounts(1);
        } else if (resp.status === 409 && data.status === 'duplicate') {
          show(dupBox);
          setText(dupMsg, data.error || 'An existing source appears to contain the same material.');
          if (viewExisting && data.duplicate_id) viewExisting.href = `/sources/${data.duplicate_id}`;
        } else {
          show(errorBox);
          setText(errorMsg, data.error || 'Failed to save note.');
        }
      } catch {
        show(errorBox);
        setText(errorMsg, 'Network error while saving note.');
      } finally {
        if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Save Research Note'; }
      }
    }

    if (saveBtn)    saveBtn.addEventListener('click',  () => executeNote(false));
    if (forceBtn)   forceBtn.addEventListener('click', () => { hide(dupBox); executeNote(true); });
    if (anotherBtn) anotherBtn.addEventListener('click', resetNote);
    if (resetBtn)   resetBtn.addEventListener('click',   resetNote);

    function resetNote() {
      if (titleInput)  titleInput.value  = '';
      if (contentArea) contentArea.value = '';
      setText(wordsEl, '0'); setText(charsEl, '0');
      hide(errorBox); hide(dupBox); hide(successState);
      show(footer);
    }
  })();

  // ══════════════════════════════════════════════════════════════════════════
  // D. IMPORT FOLDER
  // ══════════════════════════════════════════════════════════════════════════
  (function initFolder() {
    const selectArea      = document.getElementById('cr-folder-select-area');
    const folderInput     = document.getElementById('cr-folder-input');
    const previewSection  = document.getElementById('cr-folder-preview');
    const detectedEl      = document.getElementById('cr-folder-detected');
    const supportedEl     = document.getElementById('cr-folder-supported');
    const unsupportedEl   = document.getElementById('cr-folder-unsupported');
    const readyEl         = document.getElementById('cr-folder-ready');
    const fileTable       = document.getElementById('cr-folder-file-table');
    const progressWrap    = document.getElementById('cr-folder-progress');
    const progressEntries = document.getElementById('cr-folder-progress-entries');
    const errorBox        = document.getElementById('cr-folder-error');
    const errorMsg        = document.getElementById('cr-folder-error-msg');
    const successState    = document.getElementById('cr-folder-success');
    const successStats    = document.getElementById('cr-folder-success-stats');
    const footer          = document.getElementById('cr-folder-footer');
    const importBtn       = document.getElementById('cr-folder-import-btn');
    const footerHint      = document.getElementById('cr-folder-footer-hint');
    const continueBtn     = document.getElementById('cr-folder-continue-btn');

    let readyFiles = [];

    if (selectArea) selectArea.addEventListener('click', () => { if (folderInput) folderInput.click(); });

    if (folderInput) {
      folderInput.addEventListener('change', () => {
        if (!folderInput.files || !folderInput.files.length) return;
        scanFolder(folderInput.files);
      });
    }

    function scanFolder(files) {
      const all       = Array.from(files);
      const supported = all.filter(f => isValidExt(f.name) && f.size <= MAX_FILE_SIZE);
      const unsupported = all.filter(f => !isValidExt(f.name));
      readyFiles = supported;

      setText(detectedEl,   all.length);
      setText(supportedEl,  supported.length);
      setText(unsupportedEl, unsupported.length);
      setText(readyEl,      readyFiles.length);

      if (fileTable) {
        fileTable.innerHTML = '';
        all.slice(0, 120).forEach(f => {
          const valid  = isValidExt(f.name) && f.size <= MAX_FILE_SIZE;
          const tooBig = f.size > MAX_FILE_SIZE;
          let status = 'Ready', cls = 'ok';
          if (!isValidExt(f.name)) { status = 'Unsupported'; cls = 'warn'; }
          else if (tooBig)         { status = 'Too large';    cls = 'warn'; }

          const ext   = f.name.split('.').pop().toUpperCase();
          const entry = document.createElement('div');
          entry.className = 'cr-file-entry';
          entry.innerHTML = `
            <span class="badge badge-default" style="font-size:0.6rem;">${ext}</span>
            <div style="min-width:0;">
              <div class="cr-file-name">${escapeHtml(f.name)}</div>
              <div class="cr-file-meta">${formatBytes(f.size)}</div>
            </div>
            <span class="cr-file-status ${cls}">${status}</span>
            <span></span>`;
          fileTable.appendChild(entry);
        });
        if (all.length > 120) {
          const more = document.createElement('div');
          more.className = 'cr-file-meta';
          more.style.cssText = 'padding:0.5rem 0;';
          more.textContent   = `… and ${all.length - 120} more files`;
          fileTable.appendChild(more);
        }
      }

      hide(errorBox);
      show(previewSection);

      if (importBtn) {
        importBtn.disabled = readyFiles.length === 0;
        setText(footerHint, readyFiles.length > 0
          ? `${readyFiles.length} supported file${readyFiles.length !== 1 ? 's' : ''} ready to import.`
          : 'No supported files found in this folder.');
      }
    }

    async function executeFolderImport() {
      if (!readyFiles.length) return;

      hide(previewSection);
      hide(errorBox);
      hide(footer);
      show(progressWrap);

      if (progressEntries) {
        progressEntries.innerHTML = '';
        readyFiles.forEach(f => {
          const el = document.createElement('div');
          el.className = 'cr-progress-entry pending';
          el.dataset.fname = f.name;
          el.innerHTML = `<span class="cr-progress-dot"></span>
            <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(f.name)}</span>
            <span class="cr-file-meta" style="margin-left:var(--sp-3);flex-shrink:0;"></span>`;
          progressEntries.appendChild(el);
        });
      }

      let added = 0, skipped = 0, failed = 0;

      for (const file of readyFiles) {
        const entryEl  = progressEntries ? progressEntries.querySelector(`[data-fname="${CSS.escape(file.name)}"]`) : null;
        const metaSpan = entryEl ? entryEl.querySelector('.cr-file-meta') : null;

        if (entryEl)  entryEl.className = 'cr-progress-entry active';
        if (metaSpan) metaSpan.textContent = 'Processing…';

        const fd = new FormData();
        fd.append('file', file);

        try {
          const resp = await fetch('/api/sources/import', { method: 'POST', body: fd });
          const data = await resp.json();

          if (resp.ok && data.status === 'ok') {
            added++;
            if (entryEl) entryEl.className = 'cr-progress-entry done';
            if (metaSpan) metaSpan.textContent = 'Added';
          } else if (resp.status === 409 && data.status === 'duplicate') {
            skipped++;
            if (entryEl) entryEl.className = 'cr-progress-entry dupe';
            if (metaSpan) metaSpan.textContent = 'Duplicate — skipped';
          } else {
            failed++;
            if (entryEl) entryEl.className = 'cr-progress-entry error';
            if (metaSpan) metaSpan.textContent = data.error || 'Failed';
          }
        } catch {
          failed++;
          if (entryEl) entryEl.className = 'cr-progress-entry error';
          if (metaSpan) metaSpan.textContent = 'Network error';
        }
      }

      await new Promise(r => setTimeout(r, 320));
      hide(progressWrap);
      show(successState);

      const parts = [];
      if (added)   parts.push(`<strong>${added} source${added !== 1 ? 's' : ''} added</strong>`);
      if (skipped) parts.push(`${skipped} duplicate${skipped !== 1 ? 's' : ''} skipped`);
      if (failed)  parts.push(`${failed} failed`);
      if (successStats) successStats.innerHTML = parts.join(' &nbsp;·&nbsp; ');

      updateExploreCounts(added);
    }

    if (importBtn)  importBtn.addEventListener('click', executeFolderImport);
    if (continueBtn) continueBtn.addEventListener('click', closeCapture);
  })();

})();
