/**
 * ORVIA Research Reports & Evidence Synthesis System
 * Phase 10 Interactive Document Workspace & Management Module
 */

(function () {
  'use strict';

  // ---------------------------------------------------------------------------
  // API Fetch Helper
  // ---------------------------------------------------------------------------
  async function apiCall(url, method = 'GET', body = null) {
    const options = {
      method: method,
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
    };
    if (body && (method === 'POST' || method === 'PUT')) {
      options.body = JSON.stringify(body);
    }
    const resp = await fetch(url, options);
    if (!resp.ok) {
      let errText = `HTTP ${resp.status}`;
      try {
        const errJson = await resp.json();
        errText = errJson.error || errText;
      } catch (e) {
        // Fallback
      }
      throw new Error(errText);
    }
    return resp.json();
  }

  // ---------------------------------------------------------------------------
  // Flash Message Helper
  // ---------------------------------------------------------------------------
  function showFlash(container, message, type = 'success') {
    if (!container) return;
    const el = document.createElement('div');
    el.className = `report-flash ${type}`;
    el.textContent = message;
    container.prepend(el);
    setTimeout(() => {
      el.remove();
    }, 4000);
  }

  // ---------------------------------------------------------------------------
  // 1. Report Status Tabs & Search Filter
  // ---------------------------------------------------------------------------
  function initReportStatusTabs() {
    const tabs = document.querySelectorAll('.report-status-tab[data-status-filter]');
    const cards = document.querySelectorAll('.report-card');
    const searchInput = document.getElementById('report-search-input');

    function applyFilters() {
      const activeTab = document.querySelector('.report-status-tab[data-status-filter].active');
      const statusFilter = activeTab ? activeTab.dataset.statusFilter.toLowerCase() : 'all';
      const searchVal = searchInput ? searchInput.value.toLowerCase().trim() : '';

      cards.forEach(card => {
        const cardStatus = (card.dataset.status || '').toLowerCase();
        const cardTitle = (card.dataset.title || '').toLowerCase();
        const cardSub = (card.dataset.subtitle || '').toLowerCase();

        const matchStatus = (statusFilter === 'all' || cardStatus === statusFilter);
        const matchSearch = (!searchVal || cardTitle.includes(searchVal) || cardSub.includes(searchVal));

        if (matchStatus && matchSearch) {
          card.style.display = 'flex';
        } else {
          card.style.display = 'none';
        }
      });
    }

    tabs.forEach(tab => {
      tab.addEventListener('click', function () {
        tabs.forEach(t => t.classList.remove('active'));
        this.classList.add('active');
        applyFilters();
      });
    });

    if (searchInput) {
      searchInput.addEventListener('input', applyFilters);
    }
  }

  // ---------------------------------------------------------------------------
  // 2. Report Creation Wizard (Modal Flow)
  // ---------------------------------------------------------------------------
  function initReportWizard() {
    const modal = document.getElementById('new-report-modal');
    if (!modal) return;

    // Idempotency: ensure listeners are attached exactly once
    if (modal.dataset.wizardInitialized === 'true') return;
    modal.dataset.wizardInitialized = 'true';

    // Move modal directly under document.body so it is never trapped or offset by
    // page layout containers (.page, .content) or CSS transforms
    if (modal.parentElement !== document.body) {
      document.body.appendChild(modal);
    }

    const openBtn = document.getElementById('btn-open-create-modal');
    const emptyOpenBtn = document.getElementById('btn-empty-create-report');
    const closeBtn = document.getElementById('btn-close-create-modal');
    const cancelBtn = document.getElementById('btn-cancel-create-modal');
    const buildBtn = document.getElementById('btn-build-report');
    const selectItems = modal.querySelectorAll('.section-select-item');

    let lastActiveTrigger = null;

    function openModal(trigger) {
      lastActiveTrigger = trigger || openBtn;
      modal.style.display = 'flex';
      modal.setAttribute('aria-hidden', 'false');

      // Update button state (ISSUE 2, ISSUE 5)
      if (openBtn) {
        openBtn.classList.add('is-active');
        openBtn.setAttribute('aria-expanded', 'true');
      }
      if (emptyOpenBtn) {
        emptyOpenBtn.classList.add('is-active');
        emptyOpenBtn.setAttribute('aria-expanded', 'true');
      }

      // Automatically focus first form control
      const firstInput = document.getElementById('wizard-investigation-select');
      if (firstInput) {
        setTimeout(() => {
          try {
            firstInput.focus();
          } catch (e) {
            // Ignore focus error
          }
        }, 50);
      }
    }

    function closeModal() {
      modal.style.display = 'none';
      modal.setAttribute('aria-hidden', 'true');

      // Revert button state (ISSUE 5)
      if (openBtn) {
        openBtn.classList.remove('is-active');
        openBtn.setAttribute('aria-expanded', 'false');
      }
      if (emptyOpenBtn) {
        emptyOpenBtn.classList.remove('is-active');
        emptyOpenBtn.setAttribute('aria-expanded', 'false');
      }

      if (lastActiveTrigger && typeof lastActiveTrigger.focus === 'function') {
        try {
          lastActiveTrigger.focus();
        } catch (e) {
          // Ignore
        }
      }
    }

    // Attach open handlers
    if (openBtn) {
      openBtn.addEventListener('click', function (e) {
        e.preventDefault();
        openModal(openBtn);
      });
    }

    if (emptyOpenBtn) {
      emptyOpenBtn.addEventListener('click', function (e) {
        e.preventDefault();
        openModal(emptyOpenBtn);
      });
    }

    // Attach close handlers
    if (closeBtn) {
      closeBtn.addEventListener('click', function (e) {
        e.preventDefault();
        closeModal();
      });
    }

    if (cancelBtn) {
      cancelBtn.addEventListener('click', function (e) {
        e.preventDefault();
        closeModal();
      });
    }

    // Close on click outside modal content (on the overlay backdrop)
    modal.addEventListener('click', function (e) {
      if (e.target === modal) {
        closeModal();
      }
    });

    // Close on Escape key press
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && modal.style.display === 'flex') {
        closeModal();
      }
    });

    // Toggle section choices with keyboard and mouse
    selectItems.forEach(item => {
      item.setAttribute('tabindex', '0');
      item.setAttribute('role', 'checkbox');
      item.setAttribute('aria-checked', item.classList.contains('selected') ? 'true' : 'false');

      function toggleSection() {
        item.classList.toggle('selected');
        const isSelected = item.classList.contains('selected');
        item.setAttribute('aria-checked', isSelected ? 'true' : 'false');
      }

      item.addEventListener('click', toggleSection);
      item.addEventListener('keydown', function (e) {
        if (e.key === ' ' || e.key === 'Enter') {
          e.preventDefault();
          toggleSection();
        }
      });
    });

    if (buildBtn) {
      buildBtn.addEventListener('click', async function () {
        const invSelect = document.getElementById('wizard-investigation-select');
        const titleInput = document.getElementById('wizard-report-title');
        const subtitleInput = document.getElementById('wizard-report-subtitle');

        if (!invSelect || !invSelect.value) {
          alert('Please select an investigation.');
          if (invSelect) invSelect.focus();
          return;
        }

        const selectedSections = [];
        modal.querySelectorAll('.section-select-item.selected').forEach(el => {
          if (el.dataset.sectionType) {
            selectedSections.push(el.dataset.sectionType);
          }
        });

        buildBtn.disabled = true;
        buildBtn.textContent = 'Synthesizing…';

        try {
          const payload = {
            investigation_id: invSelect.value,
            title: titleInput ? titleInput.value.trim() : null,
            subtitle: subtitleInput ? subtitleInput.value.trim() : null,
            selected_sections: selectedSections.length > 0 ? selectedSections : null,
          };
          const res = await apiCall('/api/reports', 'POST', payload);
          if (res && res.report && res.report.id) {
            window.location.href = `/reports/${res.report.id}`;
          } else {
            throw new Error('Unexpected response format.');
          }
        } catch (err) {
          alert(`Failed to create report: ${err.message}`);
          buildBtn.disabled = false;
          buildBtn.textContent = 'Assemble Research Report';
        }
      });
    }
  }

  // ---------------------------------------------------------------------------
  // 3. Section Editor (Inline edit, auto-save, reorder)
  // ---------------------------------------------------------------------------
  function initSectionEditor() {
    const list = document.getElementById('sections-editor-list');
    const flashZone = document.getElementById('report-flash-zone');
    if (!list) return;

    // Debounced text autosave
    const debounceTimers = {};

    list.addEventListener('input', function (e) {
      const target = e.target;
      const secId = target.dataset.sectionId;
      const reportId = target.dataset.reportId;
      if (!secId || !reportId) return;

      if (debounceTimers[secId]) {
        clearTimeout(debounceTimers[secId]);
      }

      debounceTimers[secId] = setTimeout(async () => {
        const card = document.querySelector(`.section-editor[data-section-id="${secId}"]`);
        if (!card) return;
        const titleInput = card.querySelector('.section-editor-title-input');
        const textInput = card.querySelector('.section-textarea');

        try {
          await apiCall(`/api/reports/${reportId}/sections/${secId}`, 'POST', {
            title: titleInput ? titleInput.value : undefined,
            content: textInput ? textInput.value : undefined,
          });
          // Update preview text if present
          const previewSec = document.getElementById(`section-${secId}`);
          if (previewSec) {
            const titleEl = previewSec.querySelector('.report-section-title');
            const contentEl = previewSec.querySelector('.report-section-content');
            if (titleEl && titleInput) {
              const posText = titleEl.textContent.split('.')[0];
              titleEl.textContent = `${posText}. ${titleInput.value}`;
            }
            if (contentEl && textInput) {
              contentEl.textContent = textInput.value;
            }
          }
        } catch (err) {
          showFlash(flashZone, `Save error: ${err.message}`, 'error');
        }
      }, 700);
    });

    // Save report title & subtitle header button
    const saveMetaBtn = document.getElementById('btn-save-report-meta');
    if (saveMetaBtn) {
      saveMetaBtn.addEventListener('click', async function () {
        const titleInput = document.getElementById('edit-report-title');
        const subInput = document.getElementById('edit-report-subtitle');
        const root = document.getElementById('report-workspace-root');
        const reportId = root ? root.dataset.reportId : null;
        if (!reportId) return;

        try {
          await apiCall(`/api/reports/${reportId}`, 'POST', {
            title: titleInput ? titleInput.value : undefined,
            subtitle: subInput ? subInput.value : undefined,
          });
          showFlash(flashZone, 'Report details updated.', 'success');
          const titleDisplay = document.getElementById('report-title-display');
          if (titleDisplay && titleInput) titleDisplay.textContent = titleInput.value;
        } catch (err) {
          showFlash(flashZone, `Error saving details: ${err.message}`, 'error');
        }
      });
    }

    // Add new section
    const submitNewSecBtn = document.getElementById('btn-submit-new-section');
    if (submitNewSecBtn) {
      submitNewSecBtn.addEventListener('click', async function () {
        const root = document.getElementById('report-workspace-root');
        const reportId = root ? root.dataset.reportId : null;
        const typeSelect = document.getElementById('new-section-type');
        const titleInput = document.getElementById('new-section-title');
        const contentInput = document.getElementById('new-section-content');

        if (!reportId || !titleInput || !titleInput.value.trim()) {
          alert('Section title is required.');
          return;
        }

        try {
          await apiCall(`/api/reports/${reportId}/sections`, 'POST', {
            section_type: typeSelect ? typeSelect.value : 'EXECUTIVE_SUMMARY',
            title: titleInput.value.trim(),
            content: contentInput ? contentInput.value.trim() : '',
          });
          window.location.reload();
        } catch (err) {
          alert(`Failed to add section: ${err.message}`);
        }
      });
    }
  }

  // ---------------------------------------------------------------------------
  // 4. Status Lifecycle Controls
  // ---------------------------------------------------------------------------
  function initStatusControls() {
    const statusBtns = document.querySelectorAll('[data-status-action]');
    statusBtns.forEach(btn => {
      btn.addEventListener('click', async function () {
        const reportId = this.dataset.reportId;
        const newStatus = this.dataset.newStatus;
        if (!reportId || !newStatus) return;

        try {
          await apiCall(`/api/reports/${reportId}/status`, 'POST', { status: newStatus });
          window.location.reload();
        } catch (err) {
          alert(`Status transition failed: ${err.message}`);
        }
      });
    });
  }

  // ---------------------------------------------------------------------------
  // 5. Delete Controls
  // ---------------------------------------------------------------------------
  function initDeleteControls() {
    // Delete report
    document.querySelectorAll('[data-delete-report]').forEach(btn => {
      btn.addEventListener('click', async function () {
        const reportId = this.dataset.reportId;
        if (!reportId) return;
        if (!confirm('Are you sure you want to delete this research report? This action cannot be undone.')) {
          return;
        }
        try {
          await apiCall(`/api/reports/${reportId}/delete`, 'POST');
          window.location.href = '/reports';
        } catch (err) {
          alert(`Failed to delete report: ${err.message}`);
        }
      });
    });

    // Delete section
    document.querySelectorAll('[data-delete-section]').forEach(btn => {
      btn.addEventListener('click', async function () {
        const secId = this.dataset.sectionId;
        const reportId = this.dataset.reportId;
        if (!secId || !reportId) return;
        if (!confirm('Remove this section from the report?')) return;

        try {
          await apiCall(`/api/reports/${reportId}/sections/${secId}/delete`, 'POST');
          const card = document.querySelector(`.section-editor[data-section-id="${secId}"]`);
          if (card) card.remove();
          const navItem = document.querySelector(`.section-nav-item[data-section-id="${secId}"]`);
          if (navItem) navItem.remove();
          const previewSec = document.getElementById(`section-${secId}`);
          if (previewSec) previewSec.remove();
        } catch (err) {
          alert(`Failed to delete section: ${err.message}`);
        }
      });
    });

    // Create new version
    const newVerBtn = document.getElementById('btn-create-version');
    if (newVerBtn) {
      newVerBtn.addEventListener('click', async function () {
        const reportId = this.dataset.reportId;
        if (!reportId) return;
        if (!confirm('Create a new version snapshot of this report?')) return;

        try {
          const res = await apiCall(`/api/reports/${reportId}/version`, 'POST', { status: 'DRAFT' });
          if (res && res.report && res.report.id) {
            window.location.href = `/reports/${res.report.id}`;
          }
        } catch (err) {
          alert(`Failed to create version: ${err.message}`);
        }
      });
    }
  }

  // ---------------------------------------------------------------------------
  // 6. Version Comparison
  // ---------------------------------------------------------------------------
  function initVersionComparison() {
    const compareBtns = document.querySelectorAll('[data-compare-version]');
    const modal = document.getElementById('diff-modal-overlay');
    const modalContent = document.getElementById('diff-modal-content');

    compareBtns.forEach(btn => {
      btn.addEventListener('click', async function () {
        const currentId = this.dataset.currentId;
        const compareId = this.dataset.compareId;
        if (!currentId || !compareId || !modal || !modalContent) return;

        modal.style.display = 'flex';
        modalContent.innerHTML = '<em style="color:#8b8984;">Computing version comparison…</em>';

        try {
          const res = await apiCall(`/api/reports/${currentId}/compare/${compareId}`);
          const diff = res.diff;

          let html = `<div style="font-size:0.85rem;color:#e2e0db;margin-bottom:1rem;">
            Comparing <strong>v${diff.version_a}</strong> vs <strong>v${diff.version_b}</strong>
          </div>`;

          // Modified sections
          if (diff.modified_sections && diff.modified_sections.length > 0) {
            html += '<div style="font-size:0.75rem;text-transform:uppercase;color:#b5c422;margin-bottom:0.4rem;">Modified Sections</div>';
            diff.modified_sections.forEach(s => {
              html += `<div style="background:#131415;padding:0.75rem;border-radius:3px;margin-bottom:0.5rem;border:1px solid rgba(255,255,255,0.06);">
                <div style="font-weight:500;color:#e2e0db;margin-bottom:0.25rem;">${s.title_b || s.section_type}</div>
                <div style="font-size:0.75rem;color:#8b8984;">Content changed: ${s.content_changed ? 'Yes' : 'No'} | Words: +${s.words_added}/-${s.words_removed}</div>
                ${s.diff_lines && s.diff_lines.length ? `<pre style="font-size:0.72rem;background:#0b0c0c;padding:0.5rem;border-radius:2px;overflow-x:auto;margin-top:0.4rem;color:#9ab568;">${s.diff_lines.slice(0, 15).join('\n')}</pre>` : ''}
              </div>`;
            });
          }

          // Added sections
          if (diff.added_sections && diff.added_sections.length > 0) {
            html += '<div style="font-size:0.75rem;text-transform:uppercase;color:#9ab568;margin-top:1rem;margin-bottom:0.4rem;">Added Sections</div>';
            diff.added_sections.forEach(s => {
              html += `<div style="font-size:0.8rem;color:#9ab568;padding:0.2rem 0;">+ ${s.title} (${s.section_type})</div>`;
            });
          }

          // Removed sections
          if (diff.removed_sections && diff.removed_sections.length > 0) {
            html += '<div style="font-size:0.75rem;text-transform:uppercase;color:#c44;margin-top:1rem;margin-bottom:0.4rem;">Removed Sections</div>';
            diff.removed_sections.forEach(s => {
              html += `<div style="font-size:0.8rem;color:#c44;padding:0.2rem 0;">- ${s.title} (${s.section_type})</div>`;
            });
          }

          modalContent.innerHTML = html;
        } catch (err) {
          modalContent.innerHTML = `<div style="color:#d47070;">Failed to load comparison: ${err.message}</div>`;
        }
      });
    });
  }

  // ---------------------------------------------------------------------------
  // 7. Provenance Panel Interaction
  // ---------------------------------------------------------------------------
  function initProvenancePanel() {
    const root = document.getElementById('report-workspace-root');
    const provContainer = document.getElementById('provenance-panel-container');
    const provContent = document.getElementById('provenance-chain-content');
    if (!root || !provContainer || !provContent) return;

    const reportId = root.dataset.reportId;

    // Listen for citation clicks or findings clicks
    document.querySelectorAll('.citation-label, [data-provenance-finding]').forEach(el => {
      el.addEventListener('click', async function () {
        const findingId = this.dataset.provenanceFinding;
        if (!findingId) return;

        provContainer.style.display = 'block';
        provContent.innerHTML = '<em style="color:#8b8984;">Tracing provenance custody…</em>';

        try {
          const res = await apiCall(`/api/reports/${reportId}/provenance/${findingId}`);
          const chain = res.provenance;
          let html = `<div class="provenance-node">
            <div class="provenance-label">FINDING</div>
            <div class="provenance-content" style="font-weight:500;">${chain.finding.title}</div>
            <div style="font-size:0.75rem;color:#8b8984;margin-top:0.25rem;">${chain.finding.statement}</div>
          </div>`;

          if (chain.evidence_chain && chain.evidence_chain.length > 0) {
            chain.evidence_chain.forEach(item => {
              html += `<div class="provenance-arrow">↓ supported by</div>
              <div class="provenance-node">
                <div class="provenance-label">EVIDENCE [${item.evidence.evidence_type}]</div>
                <div class="provenance-content">"${item.evidence.statement}"</div>
                ${item.evidence.location ? `<div style="font-size:0.7rem;color:#b5c422;">Location: ${item.evidence.location}</div>` : ''}
              </div>
              <div class="provenance-arrow">↓ primary source</div>
              <div class="provenance-node">
                <div class="provenance-label">SOURCE</div>
                <div class="provenance-content" style="color:#b5c422;">${item.source ? item.source.title : '[Unknown Source]'}</div>
              </div>`;
            });
          } else {
            html += '<div style="font-size:0.75rem;color:#c87c22;padding:0.5rem 0;">No direct empirical evidence is linked to this finding.</div>';
          }

          provContent.innerHTML = html;
        } catch (err) {
          provContent.innerHTML = `<div style="color:#d47070;">Provenance error: ${err.message}</div>`;
        }
      });
    });
  }

  // ---------------------------------------------------------------------------
  // 8. Section Navigation Smooth Scroll
  // ---------------------------------------------------------------------------
  function initSectionNavigation() {
    const navItems = document.querySelectorAll('.section-nav-item');
    navItems.forEach(item => {
      item.addEventListener('click', function (e) {
        const secId = this.dataset.sectionId;
        const target = document.getElementById(`section-${secId}`);
        if (target) {
          e.preventDefault();
          target.scrollIntoView({ behavior: 'smooth', block: 'start' });
          navItems.forEach(n => n.classList.remove('active'));
          this.classList.add('active');
        }
      });
    });
  }

  // ---------------------------------------------------------------------------
  // DOM Ready Bootstrap
  // ---------------------------------------------------------------------------
  function initAll() {
    initReportStatusTabs();
    initReportWizard();
    initSectionEditor();
    initStatusControls();
    initDeleteControls();
    initVersionComparison();
    initProvenancePanel();
    initSectionNavigation();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAll);
  } else {
    initAll();
  }
})();
