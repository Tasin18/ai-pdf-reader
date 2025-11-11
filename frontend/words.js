(function(){
  'use strict';
  const wordListEl = document.getElementById('wordList');
  const toastContainer = document.getElementById('toastContainer');
  const pdfId = localStorage.getItem('pdfId') || null;

  function showToast(message, type='success', timeout=2500){
    if (!toastContainer) return;
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = message;
    toastContainer.appendChild(el);
    setTimeout(()=>el.remove(), timeout);
  }

  function escapeHtml(s){
    return (s||'').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'}[c]));
  }

  async function load(){
    if (!pdfId){
      wordListEl.innerHTML = '<li class="meta">No PDF selected. Return to the reader.</li>';
      return;
    }
    try{
      const res = await fetch(`/api/words?pdf_id=${pdfId}`);
      const data = await res.json();
      if (!res.ok){ throw new Error(data.error || 'Failed'); }
      render(data.words || []);
    }catch(e){
      console.error(e);
      showToast('Failed to load words', 'error');
    }
  }

  function render(words){
    wordListEl.innerHTML='';
    if (!words.length){
      const empty = document.createElement('li');
      empty.className='meta';
      empty.textContent='No words yet. Select words in the reader.';
      wordListEl.appendChild(empty);
      return;
    }
    words.forEach(w => {
      const li = document.createElement('li');
      li.className='word';
      const hasData = !!w.data;
      const source = hasData && w.data && w.data._source ? String(w.data._source) : '';
      const sourceLabel = source ? (source.startsWith('error:') ? '<span class="pill" style="background:#fee2e2;color:#7f1d1d">LLM error</span>' : (source === 'cerebras' ? '<span class="pill" style="background:#dbeafe;color:#1e40af">LLM</span>' : '<span class="pill">mock</span>')) : '';
      li.innerHTML = `
        <h3><span>${w.word} ${hasData ? '<span class=\"pill\">generated</span>' : ''} ${sourceLabel}</span>
          <button data-del="${w.id}" title="Delete" style="background:#fee2e2;border:1px solid #fecaca;border-radius:6px;cursor:pointer">✕</button>
        </h3>
        ${hasData ? `
          <div class="field"><b>Definition</b><div>${escapeHtml(w.data.definition || '')}</div></div>
          <div class="field"><b>Synonyms</b><div>${(w.data.synonyms || []).join(', ')}</div></div>
          <div class="field"><b>Antonyms</b><div>${(w.data.antonyms || []).join(', ')}</div></div>
          <div class="field"><b>Example</b><div>${escapeHtml(w.data.example || '')}</div></div>
          <div class="field"><b>Bengali</b><div>${escapeHtml(w.data.meaning_bn || '')}</div></div>
        ` : '<div class="meta">Not generated yet</div>'}
      `;
      wordListEl.appendChild(li);
    });
    wordListEl.querySelectorAll('button[data-del]').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        const id = e.currentTarget.getAttribute('data-del');
        if (!id) return;
        try{
          let res = await fetch(`/api/word/${id}`, { method: 'DELETE' });
          if (res.status === 405){
            res = await fetch(`/api/word/${id}/delete`, { method: 'POST' });
          }
          const ct = res.headers.get('content-type')||'';
          let data = ct.includes('application/json') ? await res.json() : {};
          if (!res.ok || data.deleted !== true) throw new Error((data && data.error) || 'Delete failed');
          showToast('Deleted', 'success');
          await load();
        }catch(err){
          console.error(err);
          showToast('Delete failed', 'error');
        }
      });
    });
  }

  load();
})();
