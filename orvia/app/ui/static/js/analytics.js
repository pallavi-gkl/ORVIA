/**
 * ORVIA Phase 9: Research Analytics & Pattern Intelligence Client Script
 * Handles tab navigation, interactive source/concept comparators, and filter dispatches.
 */
(function () {
  'use strict';

  function initAnalyticsTabs() {
    const nav = document.querySelector('.analytics-nav');
    const tabs = Array.from(document.querySelectorAll('.analytics-nav-tab'));
    const panels = document.querySelectorAll('.analytics-tab-panel');

    if (!tabs.length) return;

    function scrollTabIntoView(tab, smooth = true) {
      if (!tab || !nav) return;
      const navRect = nav.getBoundingClientRect();
      const tabRect = tab.getBoundingClientRect();

      // Check if tab is partially or completely outside the horizontal visible range
      if (tabRect.left < navRect.left || tabRect.right > navRect.right) {
        tab.scrollIntoView({
          behavior: smooth ? 'smooth' : 'auto',
          inline: 'nearest',
          block: 'nearest'
        });
      }
    }

    // Scroll active tab into view on initial page load (e.g. if loaded via ?tab=comparisons)
    const initialActive = document.querySelector('.analytics-nav-tab.active');
    if (initialActive) {
      setTimeout(() => scrollTabIntoView(initialActive, false), 60);
    }

    tabs.forEach((tab, index) => {
      tab.addEventListener('click', (e) => {
        e.preventDefault();
        const targetTab = tab.getAttribute('data-tab');

        tabs.forEach(t => {
          t.classList.remove('active');
          t.setAttribute('aria-selected', 'false');
        });
        panels.forEach(p => p.classList.remove('active'));

        tab.classList.add('active');
        tab.setAttribute('aria-selected', 'true');
        const targetPanel = document.querySelector(`.analytics-tab-panel[data-tab="${targetTab}"]`);
        if (targetPanel) {
          targetPanel.classList.add('active');
        }

        // Auto-scroll the newly activated tab into view if needed
        scrollTabIntoView(tab, true);

        // Update URL query string without reloading
        const url = new URL(window.location);
        url.searchParams.set('tab', targetTab);
        window.history.replaceState({}, '', url);
      });

      // Keyboard navigation support: Left / Right arrows
      tab.addEventListener('keydown', (e) => {
        let nextIndex = null;
        if (e.key === 'ArrowRight') {
          nextIndex = (index + 1) % tabs.length;
        } else if (e.key === 'ArrowLeft') {
          nextIndex = (index - 1 + tabs.length) % tabs.length;
        } else if (e.key === 'Home') {
          nextIndex = 0;
        } else if (e.key === 'End') {
          nextIndex = tabs.length - 1;
        }

        if (nextIndex !== null) {
          e.preventDefault();
          const nextTab = tabs[nextIndex];
          nextTab.focus();
          nextTab.click();
        }
      });
    });

    // On window resize, keep the active tab visible
    window.addEventListener('resize', () => {
      const currentActive = document.querySelector('.analytics-nav-tab.active');
      if (currentActive) {
        scrollTabIntoView(currentActive, false);
      }
    });
  }

  function initSourceComparator() {
    const selA = document.getElementById('compare-src-a');
    const selB = document.getElementById('compare-src-b');
    const btnCompare = document.getElementById('btn-compare-sources');
    const resultBox = document.getElementById('source-comparison-result');

    if (!btnCompare || !selA || !selB || !resultBox) return;

    btnCompare.addEventListener('click', async () => {
      const srcA = selA.value;
      const srcB = selB.value;

      if (!srcA || !srcB) {
        alert('Please select two distinct sources to compare.');
        return;
      }
      if (srcA === srcB) {
        alert('Please select two different sources.');
        return;
      }

      btnCompare.disabled = true;
      btnCompare.textContent = 'Calculating…';

      try {
        const resp = await fetch(`/api/analytics/compare/sources?source_a=${encodeURIComponent(srcA)}&source_b=${encodeURIComponent(srcB)}`);
        const data = await resp.json();

        if (data.status === 'ok') {
          const comp = data.comparison;
          renderSourceComparison(resultBox, comp);
        } else {
          resultBox.innerHTML = `<div class="p-4 t-secondary">${data.error || 'Failed to compare sources.'}</div>`;
        }
      } catch (err) {
        resultBox.innerHTML = `<div class="p-4 t-secondary">Network error while computing overlap.</div>`;
      } finally {
        btnCompare.disabled = false;
        btnCompare.textContent = 'Compare Sources';
      }
    });
  }

  function renderSourceComparison(container, comp) {
    const sharedHtml = comp.shared_concepts.length
      ? comp.shared_concepts.map(c => `<span class="concept-chip-sm shared">${escapeHtml(c)}</span>`).join('')
      : '<span class="t-secondary" style="font-size:0.75rem;">None</span>';

    const uniqueAHtml = comp.unique_concepts_a.length
      ? comp.unique_concepts_a.map(c => `<span class="concept-chip-sm">${escapeHtml(c)}</span>`).join('')
      : '<span class="t-secondary" style="font-size:0.75rem;">None</span>';

    const uniqueBHtml = comp.unique_concepts_b.length
      ? comp.unique_concepts_b.map(c => `<span class="concept-chip-sm">${escapeHtml(c)}</span>`).join('')
      : '<span class="t-secondary" style="font-size:0.75rem;">None</span>';

    container.innerHTML = `
      <div class="comparison-result-card">
        <div class="overlap-score-banner">
          <div class="overlap-score-number">${comp.overlap_pct}%</div>
          <div>
            <div style="font-size:1rem;color:var(--text-primary);font-weight:500;">Concept Overlap (Jaccard Index)</div>
            <div class="overlap-score-caption">${escapeHtml(comp.explanation)}</div>
          </div>
        </div>

        <div style="margin-bottom:1rem;">
          <div class="section-label">Shared Concepts (${comp.shared_count})</div>
          <div class="concept-chip-container">${sharedHtml}</div>
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:1.5rem;margin-top:1.25rem;">
          <div>
            <div class="section-label">Unique to "${escapeHtml(comp.source_a_title)}" (${comp.unique_concepts_a.length})</div>
            <div class="concept-chip-container">${uniqueAHtml}</div>
          </div>
          <div>
            <div class="section-label">Unique to "${escapeHtml(comp.source_b_title)}" (${comp.unique_concepts_b.length})</div>
            <div class="concept-chip-container">${uniqueBHtml}</div>
          </div>
        </div>
      </div>
    `;
  }

  function initConceptComparator() {
    const selA = document.getElementById('compare-cpt-a');
    const selB = document.getElementById('compare-cpt-b');
    const btnCompare = document.getElementById('btn-compare-concepts');
    const resultBox = document.getElementById('concept-comparison-result');

    if (!btnCompare || !selA || !selB || !resultBox) return;

    btnCompare.addEventListener('click', async () => {
      const cptA = selA.value;
      const cptB = selB.value;

      if (!cptA || !cptB) {
        alert('Please select two distinct concepts to compare.');
        return;
      }
      if (cptA === cptB) {
        alert('Please select two different concepts.');
        return;
      }

      btnCompare.disabled = true;
      btnCompare.textContent = 'Comparing…';

      try {
        const resp = await fetch(`/api/analytics/compare/concepts?concept_a=${encodeURIComponent(cptA)}&concept_b=${encodeURIComponent(cptB)}`);
        const data = await resp.json();

        if (data.status === 'ok') {
          const comp = data.comparison;
          renderConceptComparison(resultBox, comp);
        } else {
          resultBox.innerHTML = `<div class="p-4 t-secondary">${data.error || 'Failed to compare concepts.'}</div>`;
        }
      } catch (err) {
        resultBox.innerHTML = `<div class="p-4 t-secondary">Network error while computing comparison.</div>`;
      } finally {
        btnCompare.disabled = false;
        btnCompare.textContent = 'Compare Concepts';
      }
    });
  }

  function renderConceptComparison(container, comp) {
    const sharedSourcesHtml = comp.shared_sources.length
      ? comp.shared_sources.map(s => `
          <div style="font-size:0.78rem;padding:0.35rem 0;border-bottom:1px solid rgba(255,255,255,0.04);display:flex;justify-content:space-between;">
            <a href="/sources/${s.id}" style="color:var(--text-primary);text-decoration:none;">${escapeHtml(s.title)}</a>
            <span class="num-cell" style="color:var(--text-muted);">${s.occurrences_a} vs ${s.occurrences_b} occ</span>
          </div>
        `).join('')
      : '<div class="t-secondary" style="font-size:0.78rem;">No shared research sources observed.</div>';

    container.innerHTML = `
      <div class="comparison-result-card">
        <div style="font-size:0.95rem;color:var(--text-primary);margin-bottom:1rem;">
          ${escapeHtml(comp.explanation)}
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:1.5rem;margin-bottom:1.5rem;">
          <div style="background:rgba(255,255,255,0.02);padding:1rem;border-radius:4px;border:1px solid rgba(255,255,255,0.06);">
            <div style="font-weight:500;font-size:1.1rem;color:var(--accent);margin-bottom:0.5rem;">${escapeHtml(comp.concept_a.name)}</div>
            <div style="font-size:0.78rem;color:var(--text-muted);margin-bottom:0.25rem;">Total Occurrences: <strong style="color:var(--text-primary);">${comp.concept_a.total_occurrences}</strong></div>
            <div style="font-size:0.78rem;color:var(--text-muted);margin-bottom:0.25rem;">Containing Sources: <strong style="color:var(--text-primary);">${comp.concept_a.source_count}</strong></div>
            <div style="font-size:0.78rem;color:var(--text-muted);">Observed Connections: <strong style="color:var(--text-primary);">${comp.concept_a.connection_count}</strong></div>
          </div>

          <div style="background:rgba(255,255,255,0.02);padding:1rem;border-radius:4px;border:1px solid rgba(255,255,255,0.06);">
            <div style="font-weight:500;font-size:1.1rem;color:var(--accent);margin-bottom:0.5rem;">${escapeHtml(comp.concept_b.name)}</div>
            <div style="font-size:0.78rem;color:var(--text-muted);margin-bottom:0.25rem;">Total Occurrences: <strong style="color:var(--text-primary);">${comp.concept_b.total_occurrences}</strong></div>
            <div style="font-size:0.78rem;color:var(--text-muted);margin-bottom:0.25rem;">Containing Sources: <strong style="color:var(--text-primary);">${comp.concept_b.source_count}</strong></div>
            <div style="font-size:0.78rem;color:var(--text-muted);">Observed Connections: <strong style="color:var(--text-primary);">${comp.concept_b.connection_count}</strong></div>
          </div>
        </div>

        <div class="section-label">Mutual Sources (${comp.shared_source_count})</div>
        <div style="margin-top:0.5rem;">${sharedSourcesHtml}</div>
      </div>
    `;
  }

  function escapeHtml(str) {
    if (!str) return '';
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  document.addEventListener('DOMContentLoaded', () => {
    initAnalyticsTabs();
    initSourceComparator();
    initConceptComparator();
  });
})();
