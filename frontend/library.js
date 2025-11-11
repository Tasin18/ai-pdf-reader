(function(){
  'use strict';
  /**
   * Library page logic: lists uploaded PDFs and allows opening/downloading.
   */
  const grid = document.getElementById('grid');
  const toastContainer = document.getElementById('toastContainer');

  /**
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
    setTimeout(() => el.remove(), timeout);
  }

  /**
   * Format ISO datetime (UTC) to local string.
   * @param {string} dt
   */
  function fmt(dt){
    if (!dt) return '';
    // dt is ISO string; show local date/time
    const d = new Date(dt + 'Z');
    return d.toLocaleString();
  }

  /**
   * Render a grid of PDFs.
   * @param {Array<any>} pdfs
   */
  function render(pdfs){
    grid.innerHTML = '';
    if (!pdfs.length){
      const empty = document.createElement('div');
      empty.textContent = 'No PDFs uploaded yet. Go back and upload one.';
      empty.style.color = '#64748b';
      grid.appendChild(empty);
      return;
    }
    pdfs.forEach(p => {
      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML = `
        <h3>${escapeHtml(p.original_name)}</h3>
        <div class="meta">Uploaded: ${fmt(p.uploaded_at)} · Words: ${p.word_count||0}</div>
        <div class="actions">
          <button class="btn primary" data-open>Open</button>
          <button class="btn" data-words>Words</button>
          <a class="btn" href="/api/pdf/${p.id}" target="_blank">Download</a>
          <button class="btn" data-del title="Delete PDF" style="background:#fee2e2;border-color:#fecaca">Delete</button>
        </div>
      `;
      const delBtn = card.querySelector('button[data-del]');
      if (delBtn){
        delBtn.addEventListener('click', async () => {
          if (!confirm('Delete this PDF and all its words?')) return;
          try {
            let res = await fetch(`/api/pdf/${p.id}`, { method: 'DELETE' });
            if (res.status === 405) {
              res = await fetch(`/api/pdf/${p.id}/delete`, { method: 'POST' });
            }
            const ct = res.headers.get('content-type')||'';
            const data = ct.includes('application/json') ? await res.json() : {};
            if (!res.ok || data.deleted !== true) throw new Error((data && data.error) || 'Delete failed');
            showToast('PDF deleted', 'success');
            await load();
          } catch (err) {
            console.error(err);
            showToast('Failed to delete PDF', 'error');
          }
        });
      }
      const openBtn = card.querySelector('button[data-open]');
      if (openBtn){
        openBtn.addEventListener('click', () => {
          localStorage.setItem('pdfId', p.id);
          location.href = '/';
        });
      }
      const wordsBtn = card.querySelector('button[data-words]');
      if (wordsBtn){
        wordsBtn.addEventListener('click', () => {
          localStorage.setItem('pdfId', p.id);
          location.href = '/words.html';
        });
      }
      grid.appendChild(card);
    });
  }

  /**
   * @param {string} s
   * @returns {string}
   */
  function escapeHtml(s) {
    return (s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'}[c]));
  }

  /** Load PDFs from backend and render them. */
  async function load(){
    try{
      const res = await fetch('/api/pdfs', { cache: 'no-store' });
      const data = await res.json();
      render((data && data.pdfs) || []);
    }catch(e){
      console.error(e);
      showToast('Failed to load library', 'error');
    }
  }

  load();
})();
