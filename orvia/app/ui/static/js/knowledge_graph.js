/**
 * ORVIA Interactive Knowledge Graph Renderer
 * Phase 7 — Interactive Knowledge Graph
 * 
 * Deterministic local SVG force-directed topology visualizer with:
 * - Zoom & pan viewport manipulation
 * - Node and edge selection
 * - Neighborhood highlight and dimming
 * - Contextual detail panel rendering with real evidence
 * - Search within graph
 * - Reduced-motion accessibility support
 */

(function (window, document) {
  'use strict';

  class KnowledgeGraphRenderer {
    constructor(svgElement, panelElement, options = {}) {
      this.svg = svgElement;
      this.panel = panelElement;
      this.options = Object.assign({
        width: 800,
        height: 600,
        nodeBaseRadius: 6,
        onNodeSelect: null,
        onEdgeSelect: null,
        onResetSelection: null,
      }, options);

      this.nodes = new Map();
      this.edges = new Map();
      this.selectedNodeId = null;
      this.selectedEdgeId = null;
      this.hoveredNodeId = null;

      // Viewport transform
      this.panX = 0;
      this.panY = 0;
      this.scale = 1.0;
      this.isPanning = false;
      this.startPan = { x: 0, y: 0 };

      // Dragging node state
      this.draggedNode = null;

      // Simulation handle
      this.simulationFrame = null;
      this.simulationAlpha = 1.0;

      this.initDom();
      this.initEvents();
    }

    initDom() {
      this.svg.innerHTML = `
        <defs>
          <pattern id="dot-grid-pattern" width="24" height="24" patternUnits="userSpaceOnUse">
            <circle cx="2" cy="2" r="1" class="graph-dot-grid" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#dot-grid-pattern)" />
        <g id="graph-viewport">
          <g id="edges-layer"></g>
          <g id="nodes-layer"></g>
        </g>
      `;
      this.viewport = this.svg.querySelector('#graph-viewport');
      this.edgesLayer = this.svg.querySelector('#edges-layer');
      this.nodesLayer = this.svg.querySelector('#nodes-layer');
    }

    initEvents() {
      // Pan with pointer down on SVG background
      this.svg.addEventListener('pointerdown', (e) => {
        if (e.target.closest('.graph-node') || e.target.closest('.graph-edge')) {
          return;
        }
        this.isPanning = true;
        this.startPan = { x: e.clientX - this.panX, y: e.clientY - this.panY };
        this.svg.setPointerCapture(e.pointerId);
      });

      this.svg.addEventListener('pointermove', (e) => {
        if (this.isPanning) {
          this.panX = e.clientX - this.startPan.x;
          this.panY = e.clientY - this.startPan.y;
          this.updateTransform();
        } else if (this.draggedNode) {
          const pt = this.clientToSvgCoords(e.clientX, e.clientY);
          this.draggedNode.x = pt.x;
          this.draggedNode.y = pt.y;
          this.updatePositions();
        }
      });

      const endPanOrDrag = (e) => {
        if (this.isPanning) {
          this.isPanning = false;
          try { this.svg.releasePointerCapture(e.pointerId); } catch (_) {}
        }
        if (this.draggedNode) {
          this.draggedNode = null;
        }
      };

      this.svg.addEventListener('pointerup', endPanOrDrag);
      this.svg.addEventListener('pointercancel', endPanOrDrag);

      // Wheel Zoom
      this.svg.addEventListener('wheel', (e) => {
        e.preventDefault();
        const zoomFactor = e.deltaY < 0 ? 1.12 : 0.89;
        const rect = this.svg.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;
        const mouseY = e.clientY - rect.top;

        const newScale = Math.max(0.25, Math.min(4.0, this.scale * zoomFactor));
        this.panX = mouseX - (mouseX - this.panX) * (newScale / this.scale);
        this.panY = mouseY - (mouseY - this.panY) * (newScale / this.scale);
        this.scale = newScale;
        this.updateTransform();
      }, { passive: false });

      // Click background to clear selection
      this.svg.addEventListener('click', (e) => {
        if (!e.target.closest('.graph-node') && !e.target.closest('.graph-edge')) {
          this.clearSelection();
        }
      });
    }

    clientToSvgCoords(clientX, clientY) {
      const rect = this.svg.getBoundingClientRect();
      const x = (clientX - rect.left - this.panX) / this.scale;
      const y = (clientY - rect.top - this.panY) / this.scale;
      return { x, y };
    }

    updateTransform() {
      this.viewport.setAttribute(
        'transform',
        `translate(${this.panX}, ${this.panY}) scale(${this.scale})`
      );
    }

    zoom(delta) {
      const newScale = Math.max(0.25, Math.min(4.0, this.scale * (delta > 0 ? 1.25 : 0.8)));
      const cx = this.svg.clientWidth / 2;
      const cy = this.svg.clientHeight / 2;
      this.panX = cx - (cx - this.panX) * (newScale / this.scale);
      this.panY = cy - (cy - this.panY) * (newScale / this.scale);
      this.scale = newScale;
      this.updateTransform();
    }

    resetView() {
      this.panX = 0;
      this.panY = 0;
      this.scale = 1.0;
      this.updateTransform();
    }

    loadGraph(data) {
      if (this.simulationFrame) {
        cancelAnimationFrame(this.simulationFrame);
        this.simulationFrame = null;
      }

      this.nodes.clear();
      this.edges.clear();
      this.selectedNodeId = null;
      this.selectedEdgeId = null;

      const width = this.svg.clientWidth || this.options.width;
      const height = this.svg.clientHeight || this.options.height;
      const nodeCount = data.nodes ? data.nodes.length : 0;

      // Position nodes initially on an orbital spiral
      (data.nodes || []).forEach((n, idx) => {
        const angle = idx * 2.39996; // Golden angle
        const radius = Math.min(width, height) * 0.35 * Math.sqrt((idx + 1) / (nodeCount + 1));
        const x = width / 2 + radius * Math.cos(angle);
        const y = height / 2 + radius * Math.sin(angle);

        this.nodes.set(n.id, Object.assign({}, n, {
          x,
          y,
          vx: 0,
          vy: 0,
          radius: Math.max(5, Math.min(18, 5 + (n.importance || 0.5) * 10 + Math.min(n.degree || 0, 8))),
        }));
      });

      // Register edges
      (data.edges || []).forEach((e) => {
        if (this.nodes.has(e.source) && this.nodes.has(e.target)) {
          this.edges.set(e.id, Object.assign({}, e));
        }
      });

      this.render();

      // Check prefers-reduced-motion
      const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      if (reducedMotion) {
        for (let i = 0; i < 90; i++) {
          this.tickSimulation(0.9);
        }
        this.updatePositions();
      } else {
        this.simulationAlpha = 1.0;
        this.runSimulation();
      }

      // If initial graph specified a focus concept, select it
      if (data.metadata && data.metadata.focus_concept_id) {
        this.selectNode(data.metadata.focus_concept_id);
      } else {
        this.renderDefaultPanel(data.metadata);
      }
    }

    runSimulation() {
      let ticks = 0;
      const maxTicks = 120;

      const step = () => {
        ticks++;
        this.simulationAlpha *= 0.95;
        this.tickSimulation(this.simulationAlpha);
        this.updatePositions();

        if (ticks < maxTicks && this.simulationAlpha > 0.03) {
          this.simulationFrame = requestAnimationFrame(step);
        } else {
          this.simulationFrame = null;
        }
      };

      this.simulationFrame = requestAnimationFrame(step);
    }

    tickSimulation(alpha) {
      const nodeList = Array.from(this.nodes.values());
      const width = this.svg.clientWidth || this.options.width;
      const height = this.svg.clientHeight || this.options.height;
      const cx = width / 2;
      const cy = height / 2;

      // 1. Center gravity pull
      for (let i = 0; i < nodeList.length; i++) {
        const n = nodeList[i];
        n.vx += (cx - n.x) * 0.015 * alpha;
        n.vy += (cy - n.y) * 0.015 * alpha;
      }

      // 2. Node-node repulsion
      const k = 65;
      const k2 = k * k;
      for (let i = 0; i < nodeList.length; i++) {
        const a = nodeList[i];
        for (let j = i + 1; j < nodeList.length; j++) {
          const b = nodeList[j];
          let dx = b.x - a.x;
          let dy = b.y - a.y;
          let dist = Math.sqrt(dx * dx + dy * dy) || 1;

          if (dist < 320) {
            const force = (k2 / (dist * dist)) * alpha * 0.7;
            const fx = (dx / dist) * force;
            const fy = (dy / dist) * force;
            a.vx -= fx;
            a.vy -= fy;
            b.vx += fx;
            b.vy += fy;
          }
        }
      }

      // 3. Edge attraction (springs)
      for (const edge of this.edges.values()) {
        const a = this.nodes.get(edge.source);
        const b = this.nodes.get(edge.target);
        if (!a || !b) continue;

        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const targetDist = 70 + (1.0 - (edge.strength || 0.5)) * 90;
        const force = (dist - targetDist) * 0.035 * (edge.strength || 0.5) * alpha;

        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        a.vx += fx;
        a.vy += fy;
        b.vx -= fx;
        b.vy -= fy;
      }

      // 4. Position update & damping
      for (let i = 0; i < nodeList.length; i++) {
        const n = nodeList[i];
        if (n === this.draggedNode) continue;
        n.x += n.vx;
        n.y += n.vy;
        n.vx *= 0.75;
        n.vy *= 0.75;
      }
    }

    render() {
      // Clear layers
      this.edgesLayer.innerHTML = '';
      this.nodesLayer.innerHTML = '';

      // Create edge SVG elements
      for (const edge of this.edges.values()) {
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('class', 'graph-edge');
        line.setAttribute('data-id', edge.id);
        line.setAttribute('stroke-width', Math.max(1, (edge.strength || 0.5) * 2.8));
        line.setAttribute('opacity', Math.max(0.18, (edge.strength || 0.5) * 0.7));

        line.addEventListener('click', (e) => {
          e.stopPropagation();
          this.selectEdge(edge.id);
        });

        edge.element = line;
        this.edgesLayer.appendChild(line);
      }

      // Create node SVG elements
      for (const node of this.nodes.values()) {
        const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        g.setAttribute('class', `graph-node ${node.node_type}`);
        g.setAttribute('data-id', node.id);
        g.setAttribute('tabindex', '0');
        g.setAttribute('role', 'button');
        g.setAttribute('aria-label', `${node.label} (${node.node_type})`);

        // Circle
        const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        circle.setAttribute('class', 'graph-node-circle');
        circle.setAttribute('r', node.radius);
        g.appendChild(circle);

        // Label
        const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        text.setAttribute('class', 'graph-node-label');
        text.setAttribute('y', node.radius + 12);
        text.textContent = node.label;
        g.appendChild(text);

        // Events
        g.addEventListener('pointerdown', (e) => {
          e.stopPropagation();
          this.draggedNode = node;
        });

        g.addEventListener('click', (e) => {
          e.stopPropagation();
          this.selectNode(node.id);
        });

        g.addEventListener('keydown', (e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            this.selectNode(node.id);
          }
        });

        g.addEventListener('mouseenter', (e) => {
          this.showTooltip(node, e);
        });

        g.addEventListener('mouseleave', () => {
          this.hideTooltip();
        });

        node.element = g;
        this.nodesLayer.appendChild(g);
      }

      this.updatePositions();
    }

    updatePositions() {
      // Update edges
      for (const edge of this.edges.values()) {
        const a = this.nodes.get(edge.source);
        const b = this.nodes.get(edge.target);
        if (a && b && edge.element) {
          edge.element.setAttribute('x1', a.x);
          edge.element.setAttribute('y1', a.y);
          edge.element.setAttribute('x2', b.x);
          edge.element.setAttribute('y2', b.y);
        }
      }

      // Update nodes
      for (const node of this.nodes.values()) {
        if (node.element) {
          node.element.setAttribute('transform', `translate(${node.x}, ${node.y})`);
        }
      }
    }

    selectNode(nodeId) {
      const node = this.nodes.get(nodeId);
      if (!node) return;

      this.selectedNodeId = nodeId;
      this.selectedEdgeId = null;

      // Find direct neighbors
      const neighborIds = new Set([nodeId]);
      const connectedEdgeIds = new Set();

      for (const edge of this.edges.values()) {
        if (edge.source === nodeId || edge.target === nodeId) {
          neighborIds.add(edge.source);
          neighborIds.add(edge.target);
          connectedEdgeIds.add(edge.id);
        }
      }

      // Highlight/dim nodes
      for (const n of this.nodes.values()) {
        if (n.element) {
          if (n.id === nodeId) {
            n.element.classList.add('selected');
            n.element.classList.remove('dimmed');
          } else if (neighborIds.has(n.id)) {
            n.element.classList.remove('selected');
            n.element.classList.remove('dimmed');
          } else {
            n.element.classList.remove('selected');
            n.element.classList.add('dimmed');
          }
        }
      }

      // Highlight/dim edges
      for (const e of this.edges.values()) {
        if (e.element) {
          if (connectedEdgeIds.has(e.id)) {
            e.element.classList.add('selected');
            e.element.classList.remove('dimmed');
          } else {
            e.element.classList.remove('selected');
            e.element.classList.add('dimmed');
          }
        }
      }

      // Render context panel
      this.renderNodeDetailPanel(node, neighborIds, connectedEdgeIds);
    }

    selectEdge(edgeId) {
      const edge = this.edges.get(edgeId);
      if (!edge) return;

      this.selectedEdgeId = edgeId;
      this.selectedNodeId = null;

      const a = this.nodes.get(edge.source);
      const b = this.nodes.get(edge.target);

      // Highlight endpoints & edge
      for (const n of this.nodes.values()) {
        if (n.element) {
          if (n.id === edge.source || n.id === edge.target) {
            n.element.classList.add('selected');
            n.element.classList.remove('dimmed');
          } else {
            n.element.classList.remove('selected');
            n.element.classList.add('dimmed');
          }
        }
      }

      for (const e of this.edges.values()) {
        if (e.element) {
          if (e.id === edgeId) {
            e.element.classList.add('selected');
            e.element.classList.remove('dimmed');
          } else {
            e.element.classList.remove('selected');
            e.element.classList.add('dimmed');
          }
        }
      }

      this.renderEdgeDetailPanel(edge, a, b);
    }

    clearSelection() {
      this.selectedNodeId = null;
      this.selectedEdgeId = null;

      for (const n of this.nodes.values()) {
        if (n.element) {
          n.element.classList.remove('selected');
          n.element.classList.remove('dimmed');
        }
      }

      for (const e of this.edges.values()) {
        if (e.element) {
          e.element.classList.remove('selected');
          e.element.classList.remove('dimmed');
        }
      }

      this.renderDefaultPanel();
    }

    centerOnNode(nodeId) {
      const node = this.nodes.get(nodeId);
      if (!node) return;

      const cx = this.svg.clientWidth / 2;
      const cy = this.svg.clientHeight / 2;
      this.panX = cx - node.x * this.scale;
      this.panY = cy - node.y * this.scale;
      this.updateTransform();
      this.selectNode(nodeId);
    }

    // ── DETAIL PANEL RENDERING ──────────────────────────────────────────────

    renderDefaultPanel(metadata) {
      if (!this.panel) return;

      const totalNodes = this.nodes.size;
      const totalEdges = this.edges.size;

      // Top hubs
      const hubs = Array.from(this.nodes.values())
        .sort((a, b) => (b.degree || 0) - (a.degree || 0))
        .slice(0, 5);

      this.panel.innerHTML = `
        <div class="graph-panel-header">
          <div>
            <div class="t-label t-accent mb-1">TOPOLOGY OVERVIEW</div>
            <h3 class="t-h3" style="font-size: var(--text-base);">Research Network</h3>
          </div>
        </div>
        <div class="graph-panel-body">
          <div class="metadata-grid mb-4">
            <div class="meta-row">
              <span class="meta-key">Visible Concepts:</span>
              <span class="meta-val t-mono">${totalNodes}</span>
            </div>
            <div class="meta-row">
              <span class="meta-key">Observed Connections:</span>
              <span class="meta-val t-mono">${totalEdges}</span>
            </div>
          </div>

          <div class="t-label mb-2">MOST CONNECTED CONCEPTS</div>
          <div class="flex flex-col gap-2 mb-6">
            ${hubs.map(h => `
              <div class="card-editorial p-2 flex items-center justify-between" style="cursor: pointer; padding: 8px 10px;" data-focus-id="${h.id}">
                <div>
                  <div class="t-primary font-medium" style="font-size: var(--text-xs);">${h.label}</div>
                  <div class="t-muted" style="font-size: 10px;">${h.source_count} source(s) · ${h.occurrence_count} occurrences</div>
                </div>
                <span class="badge" style="font-size: 10px; font-family: var(--font-mono);">${h.degree} links</span>
              </div>
            `).join('')}
          </div>

          <div class="t-label mb-2">GRAPH GUIDE</div>
          <div class="card-editorial p-3 t-secondary" style="font-size: 11px; line-height: 1.5;">
            <p class="mb-2">● <strong>Concept Nodes:</strong> Sized by collection occurrences and degree.</p>
            <p class="mb-2">━ <strong>Edges:</strong> Thickness indicates observed relationship strength.</p>
            <p>Select any concept node or connection line to inspect supporting research evidence.</p>
          </div>
        </div>
      `;

      // Attach clicks to hubs
      this.panel.querySelectorAll('[data-focus-id]').forEach(el => {
        el.addEventListener('click', () => {
          this.centerOnNode(el.getAttribute('data-focus-id'));
        });
      });
    }

    renderNodeDetailPanel(node, neighborIds, edgeIds) {
      if (!this.panel) return;

      const relationships = [];
      for (const eid of edgeIds) {
        const edge = this.edges.get(eid);
        if (!edge) continue;
        const otherId = edge.source === node.id ? edge.target : edge.source;
        const otherNode = this.nodes.get(otherId);
        if (otherNode) {
          relationships.push({
            edge,
            node: otherNode,
          });
        }
      }
      relationships.sort((a, b) => (b.edge.strength || 0) - (a.edge.strength || 0));

      this.panel.innerHTML = `
        <div class="graph-panel-header">
          <div>
            <div class="t-label t-accent mb-1">${node.node_type.toUpperCase()}</div>
            <h3 class="t-h3" style="font-size: var(--text-base);">${node.label}</h3>
          </div>
          <button class="panel-close-btn" id="close-panel-btn" title="Clear selection">✕</button>
        </div>
        <div class="graph-panel-body">
          <div class="metadata-grid mb-4">
            <div class="meta-row">
              <span class="meta-key">Occurrences:</span>
              <span class="meta-val t-mono">${node.occurrence_count}</span>
            </div>
            <div class="meta-row">
              <span class="meta-key">Sources:</span>
              <span class="meta-val t-mono">${node.source_count}</span>
            </div>
            <div class="meta-row">
              <span class="meta-key">Connections:</span>
              <span class="meta-val t-mono">${relationships.length}</span>
            </div>
          </div>

          <div class="t-label mb-2">OBSERVED RELATIONSHIPS</div>
          ${relationships.length > 0 ? `
            <div class="flex flex-col gap-2 mb-6" style="max-height: 220px; overflow-y: auto;">
              ${relationships.map(r => `
                <div class="card-editorial p-2" style="cursor: pointer;" data-focus-id="${r.node.id}">
                  <div class="flex items-center justify-between mb-1">
                    <span class="t-primary font-medium" style="font-size: var(--text-xs);">${r.node.label}</span>
                    <span class="t-mono t-accent" style="font-size: 10px;">${r.edge.strength_score || Math.round((r.edge.strength||0)*100)}%</span>
                  </div>
                  <div class="t-muted" style="font-size: 10px;">${r.edge.strength_label} · ${r.edge.evidence_count} shared source(s)</div>
                </div>
              `).join('')}
            </div>
          ` : `
            <p class="t-muted mb-4" style="font-size: var(--text-xs);">No strong co-occurrences meeting the current filter.</p>
          `}

          <div class="flex flex-col gap-2 mt-4">
            <a href="/concepts/${node.id}" class="btn btn-secondary btn-sm" style="width: 100%; justify-content: center;">
              Open Concept Detail →
            </a>
            <a href="/search?q=${encodeURIComponent(node.label)}" class="btn btn-ghost btn-sm" style="width: 100%; justify-content: center;">
              Search across Sources →
            </a>
          </div>
        </div>
      `;

      const closeBtn = this.panel.querySelector('#close-panel-btn');
      if (closeBtn) closeBtn.addEventListener('click', () => this.clearSelection());

      this.panel.querySelectorAll('[data-focus-id]').forEach(el => {
        el.addEventListener('click', () => {
          this.centerOnNode(el.getAttribute('data-focus-id'));
        });
      });
    }

    async renderEdgeDetailPanel(edge, nodeA, nodeB) {
      if (!this.panel) return;

      this.panel.innerHTML = `
        <div class="graph-panel-header">
          <div>
            <div class="t-label t-accent mb-1">RELATIONSHIP EVIDENCE</div>
            <h3 class="t-h3" style="font-size: var(--text-xs);">${nodeA.label} ↔ ${nodeB.label}</h3>
          </div>
          <button class="panel-close-btn" id="close-panel-btn">✕</button>
        </div>
        <div class="graph-panel-body">
          <div class="t-label mb-1">OBSERVED STRENGTH</div>
          <div class="t-primary font-medium" style="font-size: var(--text-sm);">${edge.strength_label}</div>
          <div class="relationship-strength-meter">
            <div class="relationship-strength-fill" style="width: ${edge.strength_score || Math.round(edge.strength * 100)}%;"></div>
          </div>

          <p class="t-secondary mb-4" style="font-size: var(--text-xs);">
            ${edge.explanation}
          </p>

          <div class="t-label mb-2">SHARED RESEARCH SOURCES</div>
          <div id="evidence-sources-list" class="flex flex-col gap-2">
            <span class="t-muted" style="font-size: 11px;">Loading source evidence...</span>
          </div>
        </div>
      `;

      const closeBtn = this.panel.querySelector('#close-panel-btn');
      if (closeBtn) closeBtn.addEventListener('click', () => this.clearSelection());

      // Fetch evidence sources from API
      try {
        const resp = await fetch(`/api/knowledge/graph/relationship/${nodeA.id}/${nodeB.id}`);
        const data = await resp.json();
        const container = this.panel.querySelector('#evidence-sources-list');
        if (!container) return;

        if (data.status === 'ok' && data.relationship && data.relationship.evidence_sources && data.relationship.evidence_sources.length > 0) {
          container.innerHTML = data.relationship.evidence_sources.map(src => `
            <a href="/sources/${src.source_id}" class="card-editorial p-2" style="text-decoration: none; display: block;">
              <div class="t-primary font-medium hover-accent" style="font-size: var(--text-xs);">${src.source_title}</div>
              <div class="t-muted" style="font-size: 10px; margin-top: 2px;">
                ${src.occurrences_a} × ${nodeA.label}, ${src.occurrences_b} × ${nodeB.label}
              </div>
            </a>
          `).join('');
        } else {
          container.innerHTML = `<p class="t-muted" style="font-size: 11px;">No specific shared source evidence found.</p>`;
        }
      } catch (err) {
        const container = this.panel.querySelector('#evidence-sources-list');
        if (container) {
          container.innerHTML = `<p class="t-muted" style="font-size: 11px;">Unable to load supporting source records.</p>`;
        }
      }
    }

    showTooltip(node, event) {
      let tt = document.getElementById('graph-tooltip-box');
      if (!tt) {
        tt = document.createElement('div');
        tt.id = 'graph-tooltip-box';
        tt.className = 'graph-tooltip';
        document.body.appendChild(tt);
      }
      tt.innerHTML = `
        <div class="graph-tooltip-title">${node.label}</div>
        <div class="graph-tooltip-meta">${node.occurrence_count} occurrences · ${node.source_count} sources</div>
        <div class="graph-tooltip-meta">${node.degree} observed connections</div>
      `;
      tt.style.left = `${event.pageX + 12}px`;
      tt.style.top = `${event.pageY + 12}px`;
      tt.style.display = 'block';
    }

    hideTooltip() {
      const tt = document.getElementById('graph-tooltip-box');
      if (tt) tt.style.display = 'none';
    }
  }

  // Export
  window.KnowledgeGraphRenderer = KnowledgeGraphRenderer;

})(window, document);
