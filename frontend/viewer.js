(function(){
  'use strict';
  /**
   * PDF viewer UI logic
   *
   * Responsibilities:
   * - Load/display PDFs with PDF.js PDFViewer
   * - Capture selected words and sync with backend
   * - Provide zoom, paging, and keyboard shortcuts
   */
  const fileInput = document.getElementById('fileInput');
  const uploadBtn = document.getElementById('uploadBtn');
  const uploadStatus = document.getElementById('uploadStatus');
  const viewerContainer = document.getElementById('viewerContainer');
  const prevBtn = document.getElementById('prevPage');
  const nextBtn = document.getElementById('nextPage');
  const pageInfo = document.getElementById('pageInfo');
  const refreshWordPanelBtn = document.getElementById('refreshWordPanel');
  const openAllWordsBtn = document.getElementById('openAllWords');
  const singleWordPanel = document.getElementById('singleWordPanel');
  const controls = document.getElementById('pdfControls');
  const toastContainer = document.getElementById('toastContainer');
  const zoomInBtn = document.getElementById('zoomIn');
  const zoomOutBtn = document.getElementById('zoomOut');
  const scaleModeSel = document.getElementById('scaleMode');
  // Removed LLM status/test elements
  const toggleHighlightBtn = document.getElementById('toggleHighlight');
  const highlightColorSel = document.getElementById('highlightColor');
  const saveHighlightsBtn = document.getElementById('saveHighlights');
  const toggleEraserBtn = document.getElementById('toggleEraser');
  const eraseModeSel = document.getElementById('eraseMode');
  const gotoPageInput = document.getElementById('gotoPageInput');
  const gotoPageBtn = document.getElementById('gotoPageBtn');
  const tocPane = document.getElementById('tocPane');
  const toggleTocBtn = document.getElementById('toggleToc');

  const state = {
    pdfId: localStorage.getItem('pdfId') || null,
    pdfDoc: null,
    currentPage: 1,
    totalPages: 0,
    scale: 1.25,
    highlightMode: false,
    eraserMode: false,
    pendingHighlights: [], // {page, color:[r,g,b], rects:[{left,top,width,height,pageNumber}]}
  };

  const pdfjsLib = window.pdfjsLib || window['pdfjs-dist/build/pdf'];
  const pdfjsViewer = (window.pdfjsViewer) || (window['pdfjs-dist/web/pdf_viewer']);
  // Configure worker if pdfjs is present; otherwise show a toast and disable viewer actions
  if (pdfjsLib && pdfjsLib.GlobalWorkerOptions) {
    pdfjsLib.GlobalWorkerOptions.workerSrc = '/static/vendor/pdf.worker.min.js';
  } else {
    console.error('PDF.js failed to load.');
    // Minimal resilience: viewer remains but PDF loading will no-op.
  }

  // LLM status refresh removed

  /**
   * Show a small toast message.
   * @param {string} message
   * @param {'success'|'error'} [type]
   * @param {number} [timeout]
   */
  function showToast(message, type='success', timeout=2500){
    if (!toastContainer) return;
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = message;
    toastContainer.appendChild(el);
    setTimeout(() => {
      el.remove();
    }, timeout);
  }

  /** Upload a selected PDF and persist it. */
  async function upload() {
    const file = fileInput.files && fileInput.files[0];
    if (!file) { showToast('Select a PDF first', 'error'); return; }
    const form = new FormData();
    form.append('file', file);
    uploadStatus.textContent = 'Uploading...';
    try{
      const res = await fetch('/api/upload', { method: 'POST', body: form });
      const data = await res.json();
      if (!res.ok) { uploadStatus.textContent = data.error || 'Upload failed'; showToast(data.error || 'Upload failed', 'error'); return; }
      state.pdfId = data.pdf_id;
      localStorage.setItem('pdfId', state.pdfId);
      uploadStatus.textContent = 'Uploaded ✓';
      showToast('Upload successful', 'success');
      // Navigate to Library shortly so user can see it listed
      setTimeout(() => { location.href = '/library.html'; }, 700);
    }catch(e){
      console.error(e);
      uploadStatus.textContent = 'Upload failed';
      showToast('Upload failed', 'error');
    }
  }

  let pdfViewerInstance = null;
  let eventBus = null;
  let linkService = null;
  let loadingTaskRef = null;

  /**
   * Lazily instantiate the PDF.js PDFViewer bound to the container.
   * @returns {any}
   */
  function ensurePdfViewer() {
    if (!pdfjsViewer) return null;
    if (pdfViewerInstance) return pdfViewerInstance;
    // Ensure inner viewer element exists
    let inner = viewerContainer.querySelector('.pdfViewer');
    if (!inner) {
      inner = document.createElement('div');
      inner.id = 'viewer';
      inner.className = 'pdfViewer';
      viewerContainer.innerHTML = '';
      viewerContainer.appendChild(inner);
    }
    eventBus = new pdfjsViewer.EventBus();
    linkService = new pdfjsViewer.PDFLinkService({ eventBus });
    const pdfViewer = new pdfjsViewer.PDFViewer({
      container: viewerContainer,
      eventBus,
      linkService,
      textLayerMode: 2,
    });
    linkService.setViewer(pdfViewer);
    // Update page info when page changes
    eventBus.on('pagesloaded', (evt) => {
      // Ensure a comfortable initial zoom
      pdfViewer.currentScaleValue = 'page-width';
      state.totalPages = pdfViewer.pagesCount || state.totalPages;
      pageInfo.textContent = `Page ${state.currentPage} / ${state.totalPages}`;
    });
    eventBus.on('pagechanging', (evt) => {
      state.currentPage = evt.pageNumber;
      pageInfo.textContent = `Page ${state.currentPage} / ${state.totalPages}`;
      if (gotoPageInput) gotoPageInput.value = String(state.currentPage);
      if (state.pdfId) {
        try { localStorage.setItem('pdfLastPage:' + state.pdfId, String(state.currentPage)); } catch(_) {}
      }
    });
    pdfViewerInstance = pdfViewer;
    return pdfViewerInstance;
  }

  function teardownPdfViewer(){
    try {
      if (pdfViewerInstance && typeof pdfViewerInstance.cleanup === 'function') {
        pdfViewerInstance.cleanup();
      }
      if (pdfViewerInstance && pdfViewerInstance._annotationEditorUIManager &&
          typeof pdfViewerInstance._annotationEditorUIManager.destroy === 'function') {
        pdfViewerInstance._annotationEditorUIManager.destroy();
      }
    } catch(_) {}
    try { if (linkService) linkService.setDocument(null); } catch(_) {}
    if (loadingTaskRef && typeof loadingTaskRef.destroy === 'function') {
      try { loadingTaskRef.destroy(); } catch(_) {}
    }
    loadingTaskRef = null;
    pdfViewerInstance = null;
    eventBus = null;
    // Reset DOM container
    if (viewerContainer) {
      viewerContainer.innerHTML = '<div id="viewer" class="pdfViewer"></div>';
    }
  }
  function cssColorToRgb1(hex){
    // hex like #RRGGBB -> [r,g,b] 0..1
    try{
      const s = String(hex||'').trim();
      if (!s || s[0] !== '#') return [1,1,0];
      const v = parseInt(s.slice(1), 16);
      const r = (v >> 16) & 0xff, g = (v >> 8) & 0xff, b = v & 0xff;
      return [r/255, g/255, b/255];
    }catch(e){ return [1,1,0]; }
  }

  function addOverlayRect(pageDiv, rect, colorHex){
    const el = document.createElement('div');
    el.className = 'highlight-layer-mark';
    el.style.backgroundColor = colorHex || '#fff176';
    el.style.left = rect.left + 'px';
    el.style.top = rect.top + 'px';
    el.style.width = rect.width + 'px';
    el.style.height = rect.height + 'px';
    el.dataset.page = String(pageDiv.getAttribute('data-page-number')||'');
    el.dataset.left = String(rect.left);
    el.dataset.top = String(rect.top);
    el.dataset.width = String(rect.width);
    el.dataset.height = String(rect.height);
    pageDiv.appendChild(el);
  }

  function getPageDivFromNode(node){
    let el = node instanceof Element ? node : (node && node.parentElement);
    while (el && el !== viewerContainer){
      if (el.classList && el.classList.contains('page')) return el;
      el = el.parentElement;
    }
    return null;
  }

  function toPageRelativeRect(clientRect, pageDiv){
    const pageBox = pageDiv.getBoundingClientRect();
    return {
      left: clientRect.left - pageBox.left,
      top: clientRect.top - pageBox.top,
      width: clientRect.width,
      height: clientRect.height,
    };
  }

  function rectToQuadPdf(rect, pageView){
    // Convert a viewport rect (CSS px relative to pageDiv) to PDF user space quadpoints
    const vp = pageView.viewport;
    const p1 = vp.convertToPdfPoint(rect.left, rect.top); // top-left
    const p2 = vp.convertToPdfPoint(rect.left + rect.width, rect.top); // top-right
    const p3 = vp.convertToPdfPoint(rect.left, rect.top + rect.height); // bottom-left
    const p4 = vp.convertToPdfPoint(rect.left + rect.width, rect.top + rect.height); // bottom-right
    // order: x1 y1 x2 y2 x3 y3 x4 y4
    return [p1[0], p1[1], p2[0], p2[1], p3[0], p3[1], p4[0], p4[1]];
  }


  /** Load the current PDF by id and attach to the viewer. Optionally jump to desiredPage. Returns true on success. */
  async function loadPdf(desiredPage) {
    if (!state.pdfId) { return; }
    const url = `/api/pdf/${state.pdfId}?t=${Date.now()}`;
    try{
      if (!pdfjsLib || !pdfjsLib.getDocument || !pdfjsViewer) throw new Error('PDF.js unavailable');
      // Fetch bytes ourselves to get clearer errors and avoid MIME pitfalls
      const res = await fetch(url, { cache: 'no-store' });
      if (!res.ok) {
        const text = await res.text().catch(()=> '');
        throw new Error(`HTTP ${res.status} ${res.statusText}: ${text}`);
      }
      const buf = await res.arrayBuffer();
      teardownPdfViewer();
      loadingTaskRef = pdfjsLib.getDocument({ data: buf });
      state.pdfDoc = await loadingTaskRef.promise;
      state.totalPages = state.pdfDoc.numPages;
  const viewer = ensurePdfViewer();
  if (!viewer) throw new Error('PDF viewer unavailable');
  try {
	viewer.setDocument(state.pdfDoc);
  } catch(err) {
    // Fallback: hard reset viewer and try once more
    console.warn('viewer.setDocument failed, retrying with fresh viewer', err);
    teardownPdfViewer();
    const v2 = ensurePdfViewer();
    if (!v2) throw err;
    v2.setDocument(state.pdfDoc);
  }
      linkService.setDocument(state.pdfDoc);
      // Restore to desired or last viewed page
      try {
        let target = Number.isFinite(desiredPage) ? Number(desiredPage) : NaN;
        if (!Number.isFinite(target)) {
          const stored = localStorage.getItem('pdfLastPage:' + state.pdfId);
          target = stored ? parseInt(stored, 10) : NaN;
        }
        if (Number.isFinite(target) && target >= 1 && target <= state.totalPages) {
          // Set immediately and also once pages are fully laid out
          viewer.currentPageNumber = target;
          const handler = () => {
            try { viewer.currentPageNumber = target; } catch(_) {}
            if (eventBus && typeof eventBus.off === 'function') {
              eventBus.off('pagesloaded', handler);
            }
          };
          if (eventBus && typeof eventBus.on === 'function') {
            eventBus.on('pagesloaded', handler);
          }
          state.currentPage = target;
          if (gotoPageInput) gotoPageInput.value = String(target);
        }
      } catch(_) {}

      // Probe outline availability to enable/disable TOC button
      try {
        const outline = state.pdfDoc.getOutline ? await state.pdfDoc.getOutline() : null;
        if (toggleTocBtn) {
          const hasOutline = !!(outline && outline.length);
          toggleTocBtn.disabled = !hasOutline;
          toggleTocBtn.title = hasOutline ? 'Open Table of Contents' : 'No outline available';
        }
      } catch(_) { if (toggleTocBtn){ toggleTocBtn.disabled = true; toggleTocBtn.title = 'Outline error'; } }

      // If TOC is currently visible, rebuild it and preserve filter text
      if (tocPane && !tocPane.classList.contains('hidden')) {
        const existingFilter = (document.getElementById('tocFilter') && document.getElementById('tocFilter').value) || '';
        await buildToc(existingFilter);
        if (toggleTocBtn) toggleTocBtn.textContent = 'Hide TOC';
      }
    }catch(e){
      console.error('Failed to load PDF', e);
      showToast('Failed to load PDF. Try opening from Library.', 'error');
      return false;
    }
    controls.classList.remove('hidden');
    pageInfo.textContent = `Page ${state.currentPage} / ${state.totalPages}`;
    return true;
  }


  /**
   * @param {string} ch
   * @returns {boolean}
   */
  function isWordChar(ch){
    return /[A-Za-z\-']/.test(ch);
  }

  /**
   * Extract a word token from a text node at a given offset.
   * @param {Node} node
   * @param {number} offset
   * @returns {string|null}
   */
  function extractWordFromNode(node, offset){
    if (!node || node.nodeType !== Node.TEXT_NODE) return null;
    const s = node.data || '';
    if (s.length === 0) return null;
    let i = Math.max(0, Math.min(offset, s.length-1));
    if (!isWordChar(s[i]) && i>0 && isWordChar(s[i-1])) i -= 1;
    if (!isWordChar(s[i])) return null;
    let L = i, R = i;
    while (L>0 && isWordChar(s[L-1])) L--;
    while (R+1<s.length && isWordChar(s[R+1])) R++;
    const token = s.slice(L, R+1).replace(/^[-']+|[-']+$/g,'');
    if (!token || token.length>50) return null;
    return token.toLowerCase();
  }

  /** Determine the best candidate word from the current selection. */
  function getSelectedWord() {
    const sel = window.getSelection();
    if (!sel) return null;
    if (!sel.isCollapsed) {
      const text = (sel.toString()||'').trim();
      if (text) {
        const tokens = text.match(/[A-Za-z][A-Za-z\-']+/g) || [];
        const best = tokens.sort((a,b)=>b.length-a.length)[0];
        if (best) return best.toLowerCase();
      }
    }
    if (sel.rangeCount>0) {
      const r = sel.getRangeAt(0);
      const w = extractWordFromNode(r.startContainer, r.startOffset);
      if (w) return w;
    }
    return null;
  }

  /** Ensure the given word has info and render it in the single panel. */
  async function ensureAndRender(word) {
    if (!state.pdfId) return;
    try{
      const res = await fetch('/api/word/ensure', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pdf_id: state.pdfId, word })
      });
      const data = await res.json();
      if (!res.ok) {
        const msg = (data && (data.error || data.message)) || `HTTP ${res.status}`;
        if (res.status === 429) showToast('Rate limited. Please try again in a bit.', 'error');
        else showToast(`Failed: ${msg}`, 'error');
        return;
      }
      renderSingleWord(data.word);
    }catch(e){
      console.error(e);
      showToast('Failed to load word', 'error');
    }
  }

  /** Render a single word into the right panel. */
  function renderSingleWord(w){
    if (!singleWordPanel) return;
    if (!w) {
      singleWordPanel.className = 'word-single empty';
      singleWordPanel.textContent = 'Select a word in the PDF to see details';
      return;
    }
    const hasData = !!(w && w.data);
    const source = hasData && w.data && w.data._source ? String(w.data._source) : '';
    const sourceLabel = source ? (source.startsWith('error:') ? '<span class="pill" style="background:#fee2e2;color:#7f1d1d">LLM error</span>' : (source === 'cerebras' ? '<span class="pill" style="background:#dbeafe;color:#1e40af">LLM</span>' : '<span class="pill">mock</span>')) : '';
    singleWordPanel.className = 'word-single';
    singleWordPanel.innerHTML = `
      <div class="word-entry">
        <h3><span>${w.word} ${hasData ? '<span class="pill">generated</span>' : ''} ${sourceLabel}</span></h3>
        ${hasData ? `
          <div class="field"><b>Definition</b><div>${escapeHtml(w.data.definition || '')}</div></div>
          <div class="field"><b>Synonyms</b><div>${(w.data.synonyms || []).join(', ')}</div></div>
          <div class="field"><b>Antonyms</b><div>${(w.data.antonyms || []).join(', ')}</div></div>
          <div class="field"><b>Example</b><div>${escapeHtml(w.data.example || '')}</div></div>
          <div class="field"><b>Bengali</b><div>${escapeHtml(w.data.meaning_bn || '')}</div></div>
        ` : '<div class="meta">Not generated yet</div>'}
      </div>
    `;
  }

  /**
   * @param {string} s
   * @returns {string}
   */
  function escapeHtml(s) {
    return (s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'}[c]));
  }

  /** Ask backend to generate (or regenerate) info for all words. */
  async function generateAll() {
    if (!state.pdfId) return;
    const res = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // Force regenerate to replace any mock entries when a real key is present
      body: JSON.stringify({ pdf_id: state.pdfId, regenerate: true })
    });
    let data = {};
    try { data = await res.json(); } catch(_) {}
    if (!res.ok) {
      const msg = (data && (data.error || data.message)) || `HTTP ${res.status}`;
      if (res.status === 429) {
        showToast('Rate limited. Please wait a few seconds and try again.', 'error');
      } else {
        showToast(`Generate failed: ${msg}`, 'error');
      }
      return;
    }
    try {
      const cnt = data.count ?? (data.generated ? data.generated.length : 0);
      const attempted = data.attempted ?? cnt;
      const usedLLM = !!data.has_api_key;
      if (attempted === 0) {
        showToast('No words to generate. Select words in the PDF first.', 'error');
      } else if (cnt === 0) {
        showToast('Generation attempted but no outputs returned.', 'error');
      } else {
        showToast(`Generated ${cnt} entr${cnt===1?'y':'ies'}${usedLLM?' via LLM':''}`);
      }
    } catch (e) {}
    await loadWords();
  }

  // LLM test function removed

  // Events
  uploadBtn.addEventListener('click', upload);
  prevBtn.addEventListener('click', async () => {
    if (!state.pdfDoc) return;
    const viewer = pdfViewerInstance;
    if (viewer) viewer.currentPageNumber = Math.max(1, state.currentPage - 1);
  });
  nextBtn.addEventListener('click', async () => {
    if (!state.pdfDoc) return;
    const viewer = pdfViewerInstance;
    if (viewer) viewer.currentPageNumber = Math.min(state.totalPages, state.currentPage + 1);
  });
  if (zoomInBtn) {
    zoomInBtn.addEventListener('click', async () => {
      const viewer = pdfViewerInstance;
      if (!viewer) return;
      viewer.currentScale = Math.min(3.0, (viewer.currentScale || 1) + 0.15);
      if (scaleModeSel) scaleModeSel.value = 'custom';
    });
  }
  if (zoomOutBtn) {
    zoomOutBtn.addEventListener('click', async () => {
      const viewer = pdfViewerInstance;
      if (!viewer) return;
      viewer.currentScale = Math.max(0.5, (viewer.currentScale || 1) - 0.15);
      if (scaleModeSel) scaleModeSel.value = 'custom';
    });
  }

  // Page jump controls
  if (gotoPageBtn) gotoPageBtn.addEventListener('click', () => {
    const viewer = pdfViewerInstance;
    if (!viewer || !state.totalPages) return;
    const v = parseInt((gotoPageInput && gotoPageInput.value) || '1', 10);
    if (Number.isFinite(v) && v >= 1 && v <= state.totalPages) {
      viewer.currentPageNumber = v;
    } else {
      showToast(`Enter 1-${state.totalPages}`, 'error');
    }
  });
  if (gotoPageInput) gotoPageInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); gotoPageBtn && gotoPageBtn.click(); }
  });

  // Resolve outline destination to page number (fallback for direct navigation)
  async function resolveOutlinePage(item){
    if (!state.pdfDoc) return null;
    let dest = item.dest;
    try {
      if (typeof dest === 'string') {
        dest = await state.pdfDoc.getDestination(dest); // resolve named destination
      }
      if (Array.isArray(dest) && dest[0]) {
        const ref = dest[0];
        const pageIndex = await state.pdfDoc.getPageIndex(ref);
        return pageIndex + 1;
      }
    } catch(_) {}
    return null;
  }

  // TOC outline building with page fallback
  async function buildToc(presetFilter){
    if (!state.pdfDoc || !tocPane) return;
    tocPane.innerHTML = '<h3>Contents</h3><div class="meta">Loading…</div>';
    try{
      const outline = state.pdfDoc.getOutline ? await state.pdfDoc.getOutline() : null;
      if (!outline || !outline.length){
        tocPane.innerHTML = '<h3>Contents</h3><div class="meta">No outline found</div>';
        return;
      }
      const ul = document.createElement('ul');
      async function add(items, level){
        for (const item of items){
          const li = document.createElement('li');
          li.className = `lvl-${Math.min(level,3)}`;
          li.textContent = item.title || 'Untitled';
          const pageNum = await resolveOutlinePage(item);
          if (pageNum) li.dataset.pageNumber = String(pageNum);
          li.addEventListener('click', async () => {
            try {
              const p = parseInt(li.dataset.pageNumber||'0',10);
              const viewer = pdfViewerInstance;
              if (p && viewer){ viewer.currentPageNumber = p; return; }
              if (item.dest) {
                await linkService.navigateTo(item.dest);
                return;
              }
              if (item.url) window.open(item.url, '_blank');
            } catch(err){ console.warn('Outline navigation failed', err); }
          });
          ul.appendChild(li);
          if (item.items && item.items.length) await add(item.items, level+1);
        }
      }
      await add(outline,1);
      tocPane.innerHTML = '<h3>Contents</h3><input id="tocFilter" class="toc-filter" placeholder="Filter…" />';
      tocPane.appendChild(ul);
      const filterInput = document.getElementById('tocFilter');
      if (filterInput) {
        if (typeof presetFilter === 'string' && presetFilter.length) {
          filterInput.value = presetFilter;
        }
        filterInput.addEventListener('input', () => {
          const q = filterInput.value.trim().toLowerCase();
          ul.querySelectorAll('li').forEach(li => {
            li.style.display = !q || li.textContent.toLowerCase().includes(q) ? '' : 'none';
          });
        });
        // Apply initial filter if provided
        if (typeof presetFilter === 'string' && presetFilter.length) {
          const ev = new Event('input');
          filterInput.dispatchEvent(ev);
        }
      }
    }catch(err){
      tocPane.innerHTML = '<h3>Contents</h3><div class="meta">Failed to load outline</div>';
    }
  }
  if (toggleTocBtn) toggleTocBtn.addEventListener('click', async () => {
    if (!tocPane) return;
    const willShow = tocPane.classList.contains('hidden');
    tocPane.classList.toggle('hidden');
    if (willShow) await buildToc();
    toggleTocBtn.textContent = willShow ? 'Hide TOC' : 'TOC';
  });

  if (scaleModeSel) {
    scaleModeSel.addEventListener('change', () => {
      const viewer = pdfViewerInstance;
      if (!viewer) return;
      const val = scaleModeSel.value;
      if (val === 'page-width') {
        viewer.currentScaleValue = 'page-width';
      } else if (val === 'page-fit') {
        viewer.currentScaleValue = 'page-fit';
      } else if (val === 'actual') {
        // Prefer semantic value if supported; else set numeric 1.0
        try { viewer.currentScaleValue = 'page-actual'; }
        catch(e) { viewer.currentScale = 1.0; }
      }
    });
  }

  // Keyboard shortcuts: Ctrl/Meta + '+', '-', '0'
  document.addEventListener('keydown', (e) => {
    const isMod = e.ctrlKey || e.metaKey;
    if (!isMod) return;
    const tag = (e.target && e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.isComposing) return;
    const viewer = pdfViewerInstance;
    if (!viewer) return;
    if (e.key === '+' || e.key === '=') {
      e.preventDefault();
      viewer.currentScale = Math.min(3.0, (viewer.currentScale || 1) + 0.15);
      if (scaleModeSel) scaleModeSel.value = 'custom';
    } else if (e.key === '-') {
      e.preventDefault();
      viewer.currentScale = Math.max(0.5, (viewer.currentScale || 1) - 0.15);
      if (scaleModeSel) scaleModeSel.value = 'custom';
    } else if (e.key === '0') {
      e.preventDefault();
      // Reset to fit width by default
      if (scaleModeSel) scaleModeSel.value = 'page-width';
      viewer.currentScaleValue = 'page-width';
    }
  });
  viewerContainer.addEventListener('mouseup', async (e) => {
    // If eraser mode is on, skip word/selection handling here; eraser handler will run
    if (state.eraserMode) return;
    const word = getSelectedWord();
    if (state.highlightMode) {
      const sel = window.getSelection();
      if (!sel || sel.isCollapsed || sel.rangeCount === 0) return;
      const range = sel.getRangeAt(0);
      const pageDiv = getPageDivFromNode(range.startContainer);
      if (!pageDiv) return;
      const pageNumber = parseInt(pageDiv.getAttribute('data-page-number')||'0', 10);
      const pageView = pdfViewerInstance && pdfViewerInstance.getPageView(pageNumber - 1);
      if (!pageView) return;
      const rectList = Array.from(range.getClientRects());
      const colorHex = highlightColorSel ? highlightColorSel.value : '#fff176';
      const rgb = cssColorToRgb1(colorHex);
      const pending = { page: pageNumber, color: rgb, rects: [] };
      rectList.forEach(r => {
        const rel = toPageRelativeRect(r, pageDiv);
        addOverlayRect(pageDiv, rel, colorHex);
        pending.rects.push(rel);
      });
      state.pendingHighlights.push(pending);
      if (saveHighlightsBtn) saveHighlightsBtn.disabled = state.pendingHighlights.length === 0;
      sel.removeAllRanges();
      return;
    }
    if (word) {
      await ensureAndRender(word);
      window.getSelection().removeAllRanges();
    }
  });
  viewerContainer.addEventListener('dblclick', async (e) => {
    const word = getSelectedWord();
    if (word) {
      await ensureAndRender(word);
      window.getSelection().removeAllRanges();
    }
  });
  if (refreshWordPanelBtn) refreshWordPanelBtn.addEventListener('click', () => renderSingleWord(null));
  if (openAllWordsBtn) openAllWordsBtn.addEventListener('click', () => { if (state.pdfId) { localStorage.setItem('pdfId', state.pdfId); location.href = '/words.html'; } });
  // LLM test UI removed
  if (toggleHighlightBtn) toggleHighlightBtn.addEventListener('click', () => {
    state.highlightMode = !state.highlightMode;
    toggleHighlightBtn.classList.toggle('active', state.highlightMode);
    toggleHighlightBtn.textContent = state.highlightMode ? 'Highlight: ON' : 'Highlight';
    if (state.highlightMode && state.eraserMode) {
      state.eraserMode = false;
      if (toggleEraserBtn) toggleEraserBtn.classList.remove('active');
      viewerContainer.classList.remove('eraser-on');
      if (toggleEraserBtn) toggleEraserBtn.textContent = 'Erase';
    }
  });
  function undoLastPendingHighlight(){
    if (!state.pendingHighlights.length) {
      showToast('Nothing to undo', 'error');
      return;
    }
    const last = state.pendingHighlights.pop();
    // Remove overlay elements for this pending highlight
    const page = last.page;
    const pageDiv = viewerContainer.querySelector(`.page[data-page-number="${page}"]`);
    if (pageDiv) {
      last.rects.forEach(r => {
        const el = Array.from(pageDiv.querySelectorAll('.highlight-layer-mark')).find(e =>
          e.getAttribute('data-page') === String(page) &&
          Math.abs(parseFloat(e.getAttribute('data-left')||'0') - r.left) < 0.5 &&
          Math.abs(parseFloat(e.getAttribute('data-top')||'0') - r.top) < 0.5 &&
          Math.abs(parseFloat(e.getAttribute('data-width')||'0') - r.width) < 0.5 &&
          Math.abs(parseFloat(e.getAttribute('data-height')||'0') - r.height) < 0.5
        );
        if (el) el.remove();
      });
    }
    if (saveHighlightsBtn) saveHighlightsBtn.disabled = state.pendingHighlights.length === 0;
    showToast('Undid last highlight');
  }

  if (eraseModeSel) eraseModeSel.addEventListener('change', () => {
    // Turning off eraser toggle if switching to click mode
    if (eraseModeSel.value === 'click' && state.eraserMode) {
      state.eraserMode = false;
      toggleEraserBtn.classList.remove('active');
      viewerContainer.classList.remove('eraser-on');
      toggleEraserBtn.textContent = 'Erase';
    }
  });

  if (toggleEraserBtn) toggleEraserBtn.addEventListener('click', () => {
    const mode = (eraseModeSel && eraseModeSel.value) || 'click';
    if (mode === 'click') {
      // Undo last highlight operation (pending overlays)
      undoLastPendingHighlight();
      return;
    }
    // Toggle mode
    state.eraserMode = !state.eraserMode;
    toggleEraserBtn.classList.toggle('active', state.eraserMode);
    viewerContainer.classList.toggle('eraser-on', state.eraserMode);
    toggleEraserBtn.textContent = state.eraserMode ? 'Erase: ON' : 'Erase';
    if (state.eraserMode && state.highlightMode) {
      state.highlightMode = false;
      if (toggleHighlightBtn) {
        toggleHighlightBtn.classList.remove('active');
        toggleHighlightBtn.textContent = 'Highlight';
      }
    }
  });
  if (saveHighlightsBtn) saveHighlightsBtn.addEventListener('click', async () => {
    if (!state.pdfId) return;
    if (!state.pendingHighlights.length) return;
    try{
      const keepPage = state.currentPage;
      // Convert rects to quadpoints in PDF space per page
      const items = state.pendingHighlights.map(item => {
        const pageView = pdfViewerInstance && pdfViewerInstance.getPageView(item.page - 1);
        const quads = [];
        if (pageView){
          item.rects.forEach(rel => quads.push(rectToQuadPdf(rel, pageView)));
        }
        return { page: item.page, color: item.color, quads };
      });
      const res = await fetch(`/api/pdf/${state.pdfId}/highlights`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ highlights: items })
      });
      const data = await res.json().catch(()=>({}));
      if (!res.ok || data.ok !== true) throw new Error(data.error || 'Save failed');
      showToast(`Saved ${data.count||0} highlight segments`);
      state.pendingHighlights = [];
      if (saveHighlightsBtn) saveHighlightsBtn.disabled = true;
      // Robust reload with small backoff retries (handles brief file locks)
      for (let attempt=0; attempt<5; attempt++) {
        try {
          await loadPdf(keepPage);
          break;
        } catch(e) {
          if (attempt === 4) throw e;
          await new Promise(r=>setTimeout(r, 150 * (attempt+1)));
        }
      }
    }catch(err){
      console.error(err);
      showToast('Failed to save highlights', 'error');
    }
  });

  // Remove embedded highlights for current selection (eraser mode with selection + save)
  async function removeEmbeddedHighlightsFromSelection(){
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || sel.rangeCount === 0) return;
    const range = sel.getRangeAt(0);
    const pageDiv = getPageDivFromNode(range.startContainer);
    if (!pageDiv) return;
    const pageNumber = parseInt(pageDiv.getAttribute('data-page-number')||'0', 10);
    const pageView = pdfViewerInstance && pdfViewerInstance.getPageView(pageNumber - 1);
    if (!pageView) return;
    const rectList = Array.from(range.getClientRects());
    const quads = [];
    rectList.forEach(r => {
      const rel = toPageRelativeRect(r, pageDiv);
      quads.push(rectToQuadPdf(rel, pageView));
    });
    if (!quads.length) return;
    try{
      const keepPage = state.currentPage;
      const res = await fetch(`/api/pdf/${state.pdfId}/highlights/remove`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ targets: [{ page: pageNumber, quads }] })
      });
      const data = await res.json().catch(()=>({}));
      if (!res.ok || data.ok !== true) throw new Error(data.error || 'Remove failed');
      showToast(`Removed ${data.removed||0} highlight${(data.removed||0)===1?'':'s'}`);
      // Retry reload similarly
      for (let attempt=0; attempt<5; attempt++) {
        try {
          await loadPdf(keepPage);
          break;
        } catch(e) {
          if (attempt === 4) throw e;
          await new Promise(r=>setTimeout(r, 150 * (attempt+1)));
        }
      }
    }catch(e){
      console.error(e);
      showToast('Failed removing highlights', 'error');
    }finally{
      sel.removeAllRanges();
    }
  }

  viewerContainer.addEventListener('mouseup', async (e) => {
    if (state.eraserMode) {
      // If user has a selection, attempt removing embedded highlights overlapping that selection
      await removeEmbeddedHighlightsFromSelection();
    }
  });

  // Note: Overlay click-to-erase removed per new UX. Use click-undo mode or toggle+select.

  // Auto-load last PDF if present
  (async function init(){
  // LLM UI removed
    if (state.pdfId) {
      // Pass stored last page directly to reduce race with pagesloaded
      let last = NaN;
      try { last = parseInt(localStorage.getItem('pdfLastPage:' + state.pdfId)||'NaN',10); } catch(_) {}
      await loadPdf(Number.isFinite(last)? last : undefined);
      renderSingleWord(null);
      if (gotoPageInput) gotoPageInput.value = String(state.currentPage);
    }
  })();
})();
