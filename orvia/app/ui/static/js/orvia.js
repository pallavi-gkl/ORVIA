/**
 * ORVIA UI Shell Controller
 * Handles:
 * - Desktop sidebar collapse/expand with localStorage persistence
 * - Mobile navigation drawer and overlay
 * - Global Command Palette (Ctrl+K / Cmd+K) with keyboard navigation & filtering
 * - Focus traps and keyboard accessibility
 */

(function () {
  'use strict';

  // ── DOM Elements ──────────────────────────────────────────────────────────
  const shell = document.querySelector('.orvia-shell');
  const sidebar = document.getElementById('app-sidebar');
  const sidebarToggle = document.getElementById('sidebar-toggle-btn');
  const mobileMenuBtn = document.getElementById('mobile-menu-btn');
  const mobileOverlay = document.getElementById('mobile-overlay');

  const cmdTrigger = document.getElementById('cmd-search-trigger');
  const cmdOverlay = document.getElementById('cmd-palette-overlay');
  const cmdInput = document.getElementById('cmd-search-input');
  const cmdBody = document.getElementById('cmd-palette-body');
  const cmdItems = Array.from(document.querySelectorAll('.cmd-item'));

  const STORAGE_KEY_SIDEBAR = 'orvia:sidebar:collapsed';

  // ── Sidebar Collapse / Expand (Desktop) ───────────────────────────────────
  function setSidebarCollapsed(collapsed) {
    if (!shell || !sidebar) return;

    if (collapsed) {
      shell.classList.add('sidebar-collapsed');
      sidebar.classList.add('collapsed');
      if (sidebarToggle) {
        sidebarToggle.setAttribute('aria-expanded', 'false');
        sidebarToggle.setAttribute('title', 'Expand sidebar');
      }
      localStorage.setItem(STORAGE_KEY_SIDEBAR, 'true');
    } else {
      shell.classList.remove('sidebar-collapsed');
      sidebar.classList.remove('collapsed');
      if (sidebarToggle) {
        sidebarToggle.setAttribute('aria-expanded', 'true');
        sidebarToggle.setAttribute('title', 'Collapse sidebar');
      }
      localStorage.setItem(STORAGE_KEY_SIDEBAR, 'false');
    }
  }

  // Restore sidebar preference
  if (window.innerWidth > 1024) {
    const savedState = localStorage.getItem(STORAGE_KEY_SIDEBAR);
    if (savedState === 'true') {
      setSidebarCollapsed(true);
    }
  }

  if (sidebarToggle) {
    sidebarToggle.addEventListener('click', () => {
      const isCurrentlyCollapsed = sidebar.classList.contains('collapsed');
      setSidebarCollapsed(!isCurrentlyCollapsed);
    });
  }

  // ── Mobile Drawer ─────────────────────────────────────────────────────────
  function openMobileDrawer() {
    if (!sidebar || !mobileOverlay) return;
    sidebar.classList.add('mobile-open');
    mobileOverlay.classList.add('open');
    document.body.style.overflow = 'hidden';
  }

  function closeMobileDrawer() {
    if (!sidebar || !mobileOverlay) return;
    sidebar.classList.remove('mobile-open');
    mobileOverlay.classList.remove('open');
    document.body.style.overflow = '';
  }

  if (mobileMenuBtn) {
    mobileMenuBtn.addEventListener('click', openMobileDrawer);
  }

  if (mobileOverlay) {
    mobileOverlay.addEventListener('click', closeMobileDrawer);
  }

  // ── Command Palette (Ctrl+K) ──────────────────────────────────────────────
  let selectedIndex = 0;

  function getVisibleItems() {
    return Array.from(document.querySelectorAll('.cmd-item:not([style*="display: none"])'));
  }

  function updateSelectedCommand(items) {
    items.forEach((item, index) => {
      if (index === selectedIndex) {
        item.classList.add('selected');
        item.setAttribute('aria-selected', 'true');
        item.scrollIntoView({ block: 'nearest' });
      } else {
        item.classList.remove('selected');
        item.setAttribute('aria-selected', 'false');
      }
    });
  }

  function openCommandPalette() {
    if (!cmdOverlay || !cmdInput) return;
    cmdOverlay.classList.add('open');
    cmdInput.value = '';
    filterCommands('');
    cmdInput.focus();
    document.body.style.overflow = 'hidden';
  }

  function closeCommandPalette() {
    if (!cmdOverlay) return;
    cmdOverlay.classList.remove('open');
    document.body.style.overflow = '';
  }

  let searchDebounceTimer = null;
  const initialPaletteBodyHtml = cmdPaletteBody ? cmdPaletteBody.innerHTML : '';

  function filterCommands(query) {
    const q = query.trim().toLowerCase();
    const dynamicResultsContainer = document.getElementById('cmd-dynamic-results');

    if (!q || q.length < 2) {
      // Show default navigation items
      cmdItems.forEach(item => {
        item.style.display = 'flex';
      });
      if (dynamicResultsContainer) {
        dynamicResultsContainer.innerHTML = '';
        dynamicResultsContainer.style.display = 'none';
      }
      const emptyMsg = document.getElementById('cmd-empty-state');
      if (emptyMsg) emptyMsg.style.display = 'none';
      selectedIndex = 0;
      updateSelectedCommand(getVisibleItems());
      return;
    }

    // Filter local navigation items first
    let visibleCount = 0;
    cmdItems.forEach(item => {
      const text = item.textContent.trim().toLowerCase();
      const match = text.includes(q);
      item.style.display = match ? 'flex' : 'none';
      if (match) visibleCount++;
    });

    // Query universal search API with debouncing
    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = setTimeout(() => {
      fetch(`/api/universal-search?q=${encodeURIComponent(q)}`)
        .then(r => r.json())
        .then(data => {
          if (!cmdOverlay || !cmdOverlay.classList.contains('open')) return;
          renderUniversalResults(data.groups || {}, q, visibleCount);
        })
        .catch(() => {
          const emptyMsg = document.getElementById('cmd-empty-state');
          if (emptyMsg) emptyMsg.style.display = visibleCount === 0 ? 'block' : 'none';
        });
    }, 180);

    selectedIndex = 0;
    updateSelectedCommand(getVisibleItems());
  }

  function renderUniversalResults(groups, query, localMatchCount) {
    let container = document.getElementById('cmd-dynamic-results');
    if (!container && cmdPaletteBody) {
      container = document.createElement('div');
      container.id = 'cmd-dynamic-results';
      cmdPaletteBody.appendChild(container);
    }
    if (!container) return;

    const typeLabels = {
      SOURCE: 'Sources',
      CONCEPT: 'Concepts',
      INVESTIGATION: 'Investigations',
      REPORT: 'Reports',
      EVIDENCE: 'Evidence',
      FINDING: 'Findings',
    };

    let html = '';
    let totalApiResults = 0;

    Object.entries(groups).forEach(([type, items]) => {
      if (!items || !items.length) return;
      totalApiResults += items.length;
      html += `<div class="cmd-section-label">${typeLabels[type] || type}</div>`;
      items.slice(0, 4).forEach(item => {
        html += `
          <a href="${item.url}" class="cmd-item" style="display:flex;">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <circle cx="12" cy="12" r="4"></circle>
            </svg>
            <span style="flex:1;">
              <span>${item.title}</span>
              ${item.subtitle ? `<span style="display:block;font-size:0.75rem;color:var(--text-muted);margin-top:1px;">${item.subtitle}</span>` : ''}
            </span>
            <span class="badge" style="font-size:0.62rem;background:rgba(255,255,255,0.06);color:var(--text-muted);">${item.badge || type}</span>
          </a>
        `;
      });
    });

    container.innerHTML = html;
    container.style.display = html ? 'block' : 'none';

    const emptyMsg = document.getElementById('cmd-empty-state');
    if (emptyMsg) {
      emptyMsg.style.display = (localMatchCount === 0 && totalApiResults === 0) ? 'block' : 'none';
    }

    selectedIndex = 0;
    updateSelectedCommand(getVisibleItems());
  }

  if (cmdTrigger) {
    cmdTrigger.addEventListener('click', openCommandPalette);
  }

  if (cmdOverlay) {
    cmdOverlay.addEventListener('click', (e) => {
      if (e.target === cmdOverlay) {
        closeCommandPalette();
      }
    });
  }

  if (cmdInput) {
    cmdInput.addEventListener('input', (e) => {
      filterCommands(e.target.value);
    });

    cmdInput.addEventListener('keydown', (e) => {
      const visible = getVisibleItems();
      if (!visible.length) return;

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        selectedIndex = (selectedIndex + 1) % visible.length;
        updateSelectedCommand(visible);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        selectedIndex = (selectedIndex - 1 + visible.length) % visible.length;
        updateSelectedCommand(visible);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        const active = visible[selectedIndex];
        if (active) {
          const href = active.getAttribute('href');
          if (href) {
            window.location.href = href;
          } else {
            active.click();
          }
          closeCommandPalette();
        }
      }
    });
  }

  // ── Global Keyboard Shortcuts ─────────────────────────────────────────────
  window.addEventListener('keydown', (e) => {
    // Ctrl + K or Cmd + K
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      if (cmdOverlay && cmdOverlay.classList.contains('open')) {
        closeCommandPalette();
      } else {
        openCommandPalette();
      }
    }

    // Slash opens command palette when not focused in input/textarea
    if (e.key === '/' && (!cmdOverlay || !cmdOverlay.classList.contains('open'))) {
      const tag = (document.activeElement && document.activeElement.tagName) ? document.activeElement.tagName.toLowerCase() : '';
      if (tag !== 'input' && tag !== 'textarea' && tag !== 'select') {
        e.preventDefault();
        openCommandPalette();
      }
    }

    // Escape closes overlays and modals
    if (e.key === 'Escape') {
      if (cmdOverlay && cmdOverlay.classList.contains('open')) {
        closeCommandPalette();
      }
      if (sidebar && sidebar.classList.contains('mobile-open')) {
        closeMobileDrawer();
      }
      document.querySelectorAll('.modal-overlay.open').forEach(modal => {
        modal.classList.remove('open');
        document.body.style.overflow = '';
      });
    }
  });

  // Close mobile drawer upon navigating
  document.querySelectorAll('.sidebar .nav-item').forEach(link => {
    link.addEventListener('click', () => {
      if (window.innerWidth <= 768) {
        closeMobileDrawer();
      }
    });
  });

  // ═══════════════════════════════════════════════════════════════════════════
  // SOURCE INTELLIGENCE CONTROLLERS
  // ═══════════════════════════════════════════════════════════════════════════

  function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  }

  function openModal(modal) {
    if (!modal) return;
    modal.classList.add('open');
    document.body.style.overflow = 'hidden';
  }

  function closeModal(modal) {
    if (!modal) return;
    modal.classList.remove('open');
    document.body.style.overflow = '';
  }

  // Bind backdrop click to close any modal
  document.querySelectorAll('.modal-overlay').forEach(modal => {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) {
        closeModal(modal);
      }
    });
  });

  // ── Add Source Modal & Upload Pipeline ─────────────────────────────────────
  const addSourceModal = document.getElementById('add-source-modal-overlay');
  const openAddSourceBtn = document.getElementById('open-add-source-modal-btn');
  const closeAddSourceBtn = document.getElementById('close-add-source-modal-btn');
  const cancelAddSourceBtn = document.getElementById('cancel-add-source-btn');

  const fileDropzone = document.getElementById('file-dropzone');
  const fileInput = document.getElementById('source-file-input');
  const selectedFileCard = document.getElementById('selected-file-card');
  const previewExt = document.getElementById('preview-file-ext');
  const previewName = document.getElementById('preview-file-name');
  const previewSize = document.getElementById('preview-file-size');
  const customTitleInput = document.getElementById('source-custom-title');
  const removeSelectedFileBtn = document.getElementById('remove-selected-file-btn');

  const progressContainer = document.getElementById('ingest-progress-container');
  const progressStep1 = document.getElementById('p-step-1');
  const progressStep2 = document.getElementById('p-step-2');
  const progressStep3 = document.getElementById('p-step-3');
  const progressStep4 = document.getElementById('p-step-4');

  const duplicateAlert = document.getElementById('duplicate-alert');
  const duplicateAlertMsg = document.getElementById('duplicate-alert-msg');
  const viewDuplicateLink = document.getElementById('view-duplicate-link');
  const importAnywayBtn = document.getElementById('import-anyway-btn');

  const errorAlert = document.getElementById('error-alert');
  const errorAlertMsg = document.getElementById('error-alert-msg');

  const successAlert = document.getElementById('success-alert');
  const successAlertMsg = document.getElementById('success-alert-msg');
  const viewImportedSourceLink = document.getElementById('view-imported-source-link');
  const addAnotherBtn = document.getElementById('add-another-btn');

  const modalFooterActions = document.getElementById('modal-footer-actions');
  const submitImportBtn = document.getElementById('submit-import-btn');

  let currentSelectedFile = null;

  function resetAddSourceModal() {
    currentSelectedFile = null;
    if (fileInput) fileInput.value = '';
    if (customTitleInput) customTitleInput.value = '';
    if (fileDropzone) fileDropzone.style.display = 'block';
    if (selectedFileCard) selectedFileCard.style.display = 'none';
    if (progressContainer) progressContainer.style.display = 'none';
    if (duplicateAlert) duplicateAlert.style.display = 'none';
    if (errorAlert) errorAlert.style.display = 'none';
    if (successAlert) successAlert.style.display = 'none';
    if (submitImportBtn) submitImportBtn.disabled = true;
    if (modalFooterActions) modalFooterActions.style.display = 'flex';
  }

  function handleFileSelection(file) {
    if (!file) return;

    // Check extension
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    const validExts = ['.txt', '.text', '.md', '.markdown', '.csv', '.json'];
    if (!validExts.includes(ext)) {
      if (errorAlert && errorAlertMsg) {
        errorAlertMsg.textContent = 'Unsupported file format. Please upload a .txt, .csv, or .json file.';
        errorAlert.style.display = 'block';
      }
      return;
    }

    // Check size limit: 25MB
    if (file.size > 25 * 1024 * 1024) {
      if (errorAlert && errorAlertMsg) {
        errorAlertMsg.textContent = 'File exceeds 25 MB limit.';
        errorAlert.style.display = 'block';
      }
      return;
    }

    currentSelectedFile = file;

    if (errorAlert) errorAlert.style.display = 'none';
    if (duplicateAlert) duplicateAlert.style.display = 'none';
    if (successAlert) successAlert.style.display = 'none';

    let displayExt = ext.replace('.', '').toUpperCase();
    if (['MD', 'MARKDOWN', 'TEXT'].includes(displayExt)) displayExt = 'TXT';

    if (previewExt) previewExt.textContent = displayExt;
    if (previewName) previewName.textContent = file.name;
    if (previewSize) previewSize.textContent = formatBytes(file.size);

    if (fileDropzone) fileDropzone.style.display = 'none';
    if (selectedFileCard) selectedFileCard.style.display = 'block';
    if (submitImportBtn) submitImportBtn.disabled = false;
  }

  if (openAddSourceBtn) {
    openAddSourceBtn.addEventListener('click', () => {
      resetAddSourceModal();
      openModal(addSourceModal);
    });
  }

  if (closeAddSourceBtn) {
    closeAddSourceBtn.addEventListener('click', () => {
      closeModal(addSourceModal);
      resetAddSourceModal();
    });
  }

  if (cancelAddSourceBtn) {
    cancelAddSourceBtn.addEventListener('click', () => {
      closeModal(addSourceModal);
      resetAddSourceModal();
    });
  }

  // Dropzone drag-and-drop
  if (fileDropzone) {
    fileDropzone.addEventListener('click', () => {
      if (fileInput) fileInput.click();
    });

    fileDropzone.addEventListener('dragover', (e) => {
      e.preventDefault();
      fileDropzone.classList.add('dragover');
    });

    fileDropzone.addEventListener('dragleave', (e) => {
      e.preventDefault();
      fileDropzone.classList.remove('dragover');
    });

    fileDropzone.addEventListener('drop', (e) => {
      e.preventDefault();
      fileDropzone.classList.remove('dragover');
      if (e.dataTransfer && e.dataTransfer.files.length > 0) {
        handleFileSelection(e.dataTransfer.files[0]);
      }
    });
  }

  if (fileInput) {
    fileInput.addEventListener('change', () => {
      if (fileInput.files && fileInput.files.length > 0) {
        handleFileSelection(fileInput.files[0]);
      }
    });
  }

  if (removeSelectedFileBtn) {
    removeSelectedFileBtn.addEventListener('click', () => {
      resetAddSourceModal();
    });
  }

  if (addAnotherBtn) {
    addAnotherBtn.addEventListener('click', () => {
      resetAddSourceModal();
    });
  }

  // Pipeline Execution (Import)
  async function executeSourceImport(forceDuplicate = false) {
    if (!currentSelectedFile) return;

    if (duplicateAlert) duplicateAlert.style.display = 'none';
    if (errorAlert) errorAlert.style.display = 'none';
    if (successAlert) successAlert.style.display = 'none';
    if (selectedFileCard) selectedFileCard.style.display = 'none';
    if (fileDropzone) fileDropzone.style.display = 'none';
    if (modalFooterActions) modalFooterActions.style.display = 'none';

    // Show progress steps
    if (progressContainer) progressContainer.style.display = 'block';

    const setStep = (stepEl, state) => {
      if (!stepEl) return;
      stepEl.classList.remove('active', 'done');
      if (state) stepEl.classList.add(state);
    };

    setStep(progressStep1, 'active');
    setStep(progressStep2, '');
    setStep(progressStep3, '');
    setStep(progressStep4, '');

    const timer1 = setTimeout(() => {
      setStep(progressStep1, 'done');
      setStep(progressStep2, 'active');
    }, 180);

    const timer2 = setTimeout(() => {
      setStep(progressStep2, 'done');
      setStep(progressStep3, 'active');
    }, 380);

    const timer3 = setTimeout(() => {
      setStep(progressStep3, 'done');
      setStep(progressStep4, 'active');
    }, 580);

    const formData = new FormData();
    formData.append('file', currentSelectedFile);
    const customTitle = customTitleInput ? customTitleInput.value.trim() : '';
    if (customTitle) formData.append('title', customTitle);
    if (forceDuplicate) formData.append('force', 'true');

    try {
      const response = await fetch('/api/sources/import', {
        method: 'POST',
        body: formData,
      });

      clearTimeout(timer1);
      clearTimeout(timer2);
      clearTimeout(timer3);

      const data = await response.json();

      if (response.ok && data.status === 'ok') {
        setStep(progressStep1, 'done');
        setStep(progressStep2, 'done');
        setStep(progressStep3, 'done');
        setStep(progressStep4, 'done');

        setTimeout(() => {
          if (progressContainer) progressContainer.style.display = 'none';
          if (successAlert) {
            successAlert.style.display = 'block';
            if (successAlertMsg) {
              const wordsText = data.word_count ? ` · ${Number(data.word_count).toLocaleString()} words` : '';
              const conceptsText = data.concepts_found > 0 ? ` · ${data.concepts_found} concepts extracted` : '';
              successAlertMsg.textContent = `Indexed "${data.title}" (${(data.file_size / 1024).toFixed(1)} KB${wordsText}${conceptsText}). Added to research library.`;
            }
            if (viewImportedSourceLink) {
              viewImportedSourceLink.href = `/sources/${data.source_id}`;
            }
          }
        }, 250);

      } else if (response.status === 409 && data.status === 'duplicate') {
        if (progressContainer) progressContainer.style.display = 'none';
        if (duplicateAlert) {
          duplicateAlert.style.display = 'block';
          if (duplicateAlertMsg) {
            duplicateAlertMsg.textContent = data.error || 'This exact content already exists in your research workspace.';
          }
          if (viewDuplicateLink && data.duplicate_id) {
            viewDuplicateLink.href = `/sources/${data.duplicate_id}`;
          }
        }
        if (selectedFileCard) selectedFileCard.style.display = 'block';
        if (modalFooterActions) modalFooterActions.style.display = 'flex';
        if (submitImportBtn) submitImportBtn.disabled = false;

      } else {
        if (progressContainer) progressContainer.style.display = 'none';
        if (errorAlert) {
          errorAlert.style.display = 'block';
          if (errorAlertMsg) {
            errorAlertMsg.textContent = data.error || 'Failed to import source.';
          }
        }
        if (selectedFileCard) selectedFileCard.style.display = 'block';
        if (modalFooterActions) modalFooterActions.style.display = 'flex';
        if (submitImportBtn) submitImportBtn.disabled = false;
      }
    } catch (err) {
      clearTimeout(timer1);
      clearTimeout(timer2);
      clearTimeout(timer3);
      if (progressContainer) progressContainer.style.display = 'none';
      if (errorAlert) {
        errorAlert.style.display = 'block';
        if (errorAlertMsg) {
          errorAlertMsg.textContent = 'Network or server error while uploading file.';
        }
      }
      if (selectedFileCard) selectedFileCard.style.display = 'block';
      if (modalFooterActions) modalFooterActions.style.display = 'flex';
      if (submitImportBtn) submitImportBtn.disabled = false;
    }
  }

  if (submitImportBtn) {
    submitImportBtn.addEventListener('click', () => executeSourceImport(false));
  }

  if (importAnywayBtn) {
    importAnywayBtn.addEventListener('click', () => executeSourceImport(true));
  }

  // ── Seed Demo Data ────────────────────────────────────────────────────────
  async function handleSeedDemo(btn) {
    if (!btn) return;
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span>Indexing Sample Material...</span>';

    try {
      const res = await fetch('/api/sources/seed-demo', { method: 'POST' });
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        window.location.reload();
      } else {
        alert('Could not seed sample materials: ' + (data.error || 'Unknown error'));
        btn.disabled = false;
        btn.innerHTML = originalText;
      }
    } catch (e) {
      alert('Network error while requesting sample material.');
      btn.disabled = false;
      btn.innerHTML = originalText;
    }
  }

  const seedDemoBtn = document.getElementById('seed-demo-btn');
  const emptySeedDemoBtn = document.getElementById('empty-seed-demo-btn');
  if (seedDemoBtn) seedDemoBtn.addEventListener('click', () => handleSeedDemo(seedDemoBtn));
  if (emptySeedDemoBtn) emptySeedDemoBtn.addEventListener('click', () => handleSeedDemo(emptySeedDemoBtn));

  // ── Source Deletion ───────────────────────────────────────────────────────
  // List page quick delete modal
  const deleteConfirmModal = document.getElementById('delete-confirm-modal');
  const closeDeleteModalBtn = document.getElementById('close-delete-modal-btn');
  const cancelDeleteBtn = document.getElementById('cancel-delete-btn');
  const confirmDeleteBtn = document.getElementById('confirm-delete-btn');
  const deleteConfirmTitle = document.getElementById('delete-confirm-source-title');
  let pendingDeleteId = null;

  document.querySelectorAll('.source-quick-delete').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      pendingDeleteId = btn.getAttribute('data-id');
      const title = btn.getAttribute('data-title') || 'Source';
      if (deleteConfirmTitle) deleteConfirmTitle.textContent = title;
      openModal(deleteConfirmModal);
    });
  });

  if (closeDeleteModalBtn) closeDeleteModalBtn.addEventListener('click', () => closeModal(deleteConfirmModal));
  if (cancelDeleteBtn) cancelDeleteBtn.addEventListener('click', () => closeModal(deleteConfirmModal));

  if (confirmDeleteBtn) {
    confirmDeleteBtn.addEventListener('click', async () => {
      if (!pendingDeleteId) return;
      confirmDeleteBtn.disabled = true;
      confirmDeleteBtn.textContent = 'Removing...';

      try {
        const res = await fetch(`/api/sources/${pendingDeleteId}/delete`, { method: 'POST' });
        if (res.ok) {
          const card = document.querySelector(`.source-card[data-source-id="${pendingDeleteId}"]`);
          if (card) {
            card.style.transition = 'opacity 0.2s ease, transform 0.2s ease';
            card.style.opacity = '0';
            card.style.transform = 'scale(0.96)';
            setTimeout(() => {
              card.remove();
              const container = document.getElementById('sources-list-container');
              if (container && container.querySelectorAll('.source-card').length === 0) {
                window.location.reload();
              }
            }, 200);
          }
          closeModal(deleteConfirmModal);
        } else {
          alert('Could not remove source.');
        }
      } catch (e) {
        alert('Network error while removing source.');
      } finally {
        confirmDeleteBtn.disabled = false;
        confirmDeleteBtn.textContent = 'Remove Source';
        pendingDeleteId = null;
      }
    });
  }

  // Detail page removal modal
  const deleteSourceBtn = document.getElementById('delete-source-btn');
  const deleteSourceModal = document.getElementById('delete-source-modal');
  const closeDetailDeleteBtn = document.getElementById('close-detail-delete-btn');
  const cancelDetailDeleteBtn = document.getElementById('cancel-detail-delete-btn');
  const confirmDetailDeleteBtn = document.getElementById('confirm-detail-delete-btn');

  if (deleteSourceBtn && deleteSourceModal) {
    deleteSourceBtn.addEventListener('click', () => openModal(deleteSourceModal));
  }
  if (closeDetailDeleteBtn) closeDetailDeleteBtn.addEventListener('click', () => closeModal(deleteSourceModal));
  if (cancelDetailDeleteBtn) cancelDetailDeleteBtn.addEventListener('click', () => closeModal(deleteSourceModal));

  if (confirmDetailDeleteBtn && deleteSourceBtn) {
    confirmDetailDeleteBtn.addEventListener('click', async () => {
      const sourceId = deleteSourceBtn.getAttribute('data-id');
      if (!sourceId) return;
      confirmDetailDeleteBtn.disabled = true;
      confirmDetailDeleteBtn.textContent = 'Removing...';

      try {
        const res = await fetch(`/api/sources/${sourceId}/delete`, { method: 'POST' });
        if (res.ok) {
          window.location.href = '/sources';
        } else {
          alert('Failed to remove source.');
          confirmDetailDeleteBtn.disabled = false;
          confirmDetailDeleteBtn.textContent = 'Remove Source';
        }
      } catch (e) {
        alert('Network error while removing source.');
        confirmDetailDeleteBtn.disabled = false;
        confirmDetailDeleteBtn.textContent = 'Remove Source';
      }
    });
  }

  // ── Source Title Editing (Detail Page) ────────────────────────────────────
  const editTitleBtn = document.getElementById('edit-title-btn');
  const editTitleModal = document.getElementById('edit-title-modal');
  const closeEditModalBtn = document.getElementById('close-edit-modal-btn');
  const cancelEditBtn = document.getElementById('cancel-edit-btn');
  const saveEditBtn = document.getElementById('save-edit-btn');
  const editTitleInput = document.getElementById('edit-title-input');
  const sourceTitleDisplay = document.getElementById('source-title-display');

  if (editTitleBtn && editTitleModal) {
    editTitleBtn.addEventListener('click', () => {
      openModal(editTitleModal);
      if (editTitleInput) {
        setTimeout(() => editTitleInput.focus(), 50);
      }
    });
  }
  if (closeEditModalBtn) closeEditModalBtn.addEventListener('click', () => closeModal(editTitleModal));
  if (cancelEditBtn) cancelEditBtn.addEventListener('click', () => closeModal(editTitleModal));

  if (saveEditBtn && editTitleInput && deleteSourceBtn) {
    const handleSaveTitle = async () => {
      const newTitle = editTitleInput.value.trim();
      if (!newTitle) {
        alert('Title cannot be blank.');
        return;
      }
      const sourceId = deleteSourceBtn.getAttribute('data-id');
      saveEditBtn.disabled = true;
      saveEditBtn.textContent = 'Saving...';

      try {
        const res = await fetch(`/api/sources/${sourceId}/edit`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: newTitle }),
        });
        const data = await res.json();
        if (res.ok && data.status === 'ok') {
          if (sourceTitleDisplay) sourceTitleDisplay.textContent = data.title;
          document.title = `${data.title} — ORVIA`;
          closeModal(editTitleModal);
        } else {
          alert('Failed to update title: ' + (data.error || 'Unknown error'));
        }
      } catch (e) {
        alert('Network error while updating title.');
      } finally {
        saveEditBtn.disabled = false;
        saveEditBtn.textContent = 'Save Changes';
      }
    };

    saveEditBtn.addEventListener('click', handleSaveTitle);
    editTitleInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        handleSaveTitle();
      }
    });
  }

  // ── Copy Source ID / Reference ───────────────────────────────────────────
  const copyRefBtn = document.getElementById('copy-ref-btn');
  if (copyRefBtn) {
    copyRefBtn.addEventListener('click', () => {
      const sourceId = copyRefBtn.getAttribute('data-id');
      if (!sourceId) return;
      navigator.clipboard.writeText(sourceId).then(() => {
        const originalHTML = copyRefBtn.innerHTML;
        copyRefBtn.innerHTML = `
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="20 6 9 17 4 12"></polyline>
          </svg> Copied!
        `;
        copyRefBtn.style.color = 'var(--accent)';
        setTimeout(() => {
          copyRefBtn.innerHTML = originalHTML;
          copyRefBtn.style.color = '';
        }, 1800);
      });
    });
  }

  // ── Command Palette → Search Redirect ───────────────────────────────────────
  const cmdSearchInput = document.getElementById('cmd-search-input');
  if (cmdSearchInput) {
    cmdSearchInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const q = cmdSearchInput.value.trim();
        if (q.length > 0) {
          // Check if any visible command items match
          const visibleItems = document.querySelectorAll('#cmd-palette-body .cmd-item');
          let hasVisible = false;
          visibleItems.forEach(item => {
            if (item.style.display !== 'none') hasVisible = true;
          });
          // If no visible items or the empty state is showing, redirect to search
          const emptyState = document.getElementById('cmd-empty-state');
          if (!hasVisible || (emptyState && emptyState.style.display !== 'none')) {
            window.location.href = '/search?q=' + encodeURIComponent(q);
          }
        }
      }
    });
  }

  // ── Topbar Search Trigger → Search Page ──────────────────────────────────────
  const searchTrigger = document.getElementById('cmd-search-trigger');
  if (searchTrigger) {
    // Double-click on search trigger goes directly to search page
    searchTrigger.addEventListener('dblclick', (e) => {
      e.preventDefault();
      window.location.href = '/search';
    });
  }

  // ── Clear Search History ───────────────────────────────────────────────────
  const clearHistoryBtn = document.getElementById('clear-search-history-btn');
  if (clearHistoryBtn) {
    clearHistoryBtn.addEventListener('click', async () => {
      if (confirm('Clear your entire local search history?')) {
        try {
          const res = await fetch('/api/search/clear-history', { method: 'POST' });
          if (res.ok) {
            window.location.reload();
          }
        } catch (e) {
          console.error('Failed to clear search history', e);
        }
      }
    });
  }

})();

