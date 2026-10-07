/* KDP Studio — SPA (sem build). Fala com /api/* e cai em modo demo se o backend estiver fora. */
(function () {
  'use strict';
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const API = ''; // mesmo host (FastAPI serve /static + /api)

  /* ---------- toast ---------- */
  function toast(msg, type) {
    const root = $('#toast-root');
    const colors = { ok: 'border-emerald-400/40', err: 'border-rose-400/40', info: 'border-violet-400/40' };
    const icons = { ok: '✅', err: '⛔', info: '💡' };
    const el = document.createElement('div');
    el.className = `toast glass rounded-2xl px-4 py-3 text-sm border ${colors[type || 'info']} flex gap-2 items-start shadow-xl`;
    el.innerHTML = `<span>${icons[type || 'info']}</span><span>${msg}</span>`;
    root.appendChild(el);
    setTimeout(() => { el.classList.add('hide'); setTimeout(() => el.remove(), 320); }, 4200);
  }

  /* ---------- status da API ---------- */
  let apiOnline = false;
  async function checkApi() {
    const badge = $('#api-status');
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 4000);
      const r = await fetch(API + '/api/health', { signal: ctrl.signal });
      clearTimeout(t);
      apiOnline = r.ok;
    } catch { apiOnline = false; }
    if (!badge) return;
    badge.innerHTML = apiOnline
      ? '<span class="text-emerald-400">●</span> API conectada'
      : '<span class="text-amber-400">●</span> Modo demonstração';
    badge.title = apiOnline ? 'Backend FastAPI acessível' : 'Backend inacessível — usando dados de exemplo';
  }

  async function apiFetch(path, opts) {
    const r = await fetch(API + path, opts);
    if (!r.ok) {
      let detail = '';
      try { detail = (await r.json()).detail || ''; } catch { /* corpo nao-JSON */ }
      throw new Error('HTTP ' + r.status + (detail ? ' — ' + detail : ''));
    }
    const ct = r.headers.get('content-type') || '';
    return ct.includes('json') ? r.json() : r.blob();
  }

  /* ---------- provider de IA ativo ---------- */
  let apiInfo = null;
  async function loadApiInfo() {
    if (!apiOnline) return;
    try { apiInfo = await apiFetch('/api/models'); } catch { return; }
    const provider = apiInfo.provider_ativo || 'offline';
    const sel = $('#tr-model');
    if (sel && provider === 'gemini') {
      // A lista OpenAI nao vale para o Gemini: os modelos sao resolvidos no
      // servidor. Mostramos o modelo efetivo para nao enganar o usuario.
      const m = apiInfo.translation_model || 'gemini-flash-latest';
      sel.innerHTML = `<option value="${escapeAttr(m)}" selected>⚡ ${escapeHtml(m)} — Gemini (provider ativo)</option>`;
    }
    // Mesmo ajuste para o seletor de modelo do conversor (provider Gemini).
    const selConv = $('#conv-tr-model');
    if (selConv && provider === 'gemini') {
      const m = apiInfo.translation_model || 'gemini-flash-latest';
      selConv.innerHTML = `<option value="${escapeAttr(m)}" selected>⚡ ${escapeHtml(m)} — Gemini (provider ativo)</option>`;
    }
    const badge = $('#api-status');
    if (badge) {
      const nome = { openai: 'OpenAI', gemini: 'Gemini', offline: 'offline' }[provider] || provider;
      badge.innerHTML = `<span class="text-emerald-400">●</span> API conectada · ${escapeHtml(nome)}`;
      badge.title = 'Provider de IA ativo: ' + provider +
        (apiInfo.configurado ? '' : ' (sem chave — respostas mock)');
    }
  }

  /* ---------- abas ---------- */
  $$('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.tab-btn').forEach(b => { b.classList.remove('active'); b.setAttribute('aria-selected', 'false'); });
      btn.classList.add('active');
      btn.setAttribute('aria-selected', 'true');
      $$('.tab-panel').forEach(p => p.classList.remove('active'));
      $('#tab-' + btn.dataset.tab).classList.add('active');
      window.scrollTo({ top: 0, behavior: 'smooth' });
      if (btn.dataset.tab === 'library') renderLibrary();
    });
  });

  /* ============================================================
     ABA 1 — CONVERTER
  ============================================================ */
  const convState = { file: null, format: 'epub', jobId: null, chapters: [], title: '', author: '' };
  const dz = $('#dz-convert'), fileInput = $('#file-convert');

  dz.addEventListener('click', () => fileInput.click());
  dz.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') fileInput.click(); });
  ['dragenter', 'dragover'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add('drag-over'); }));
  ['dragleave', 'drop'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove('drag-over'); }));
  dz.addEventListener('drop', e => {
    const f = e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) setConvertFile(f);
  });
  fileInput.addEventListener('change', () => { if (fileInput.files[0]) setConvertFile(fileInput.files[0]); });

  function setConvertFile(f) {
    if (!/\.pdf$/i.test(f.name) && f.type !== 'application/pdf') { toast('Envie um arquivo <strong>PDF</strong>.', 'err'); return; }
    convState.file = f;
    $('#convert-filename').textContent = '📎 ' + f.name + ' (' + (f.size / 1048576).toFixed(1) + ' MB)';
    toast('Arquivo <strong>' + escapeHtml(f.name) + '</strong> pronto para converter.', 'ok');
  }

  // toggles
  [['#tg-header'], ['#tg-pagenum'], ['#tg-translate'], ['#tg-tr-export']].forEach(([sel]) => {
    const el = $(sel);
    const flip = () => { el.classList.toggle('on'); el.setAttribute('aria-checked', el.classList.contains('on')); };
    el.addEventListener('click', flip);
    el.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); flip(); } });
  });

  // painel de idiomas do conversor: só aparece com a tradução ligada
  const trOpts = $('#conv-tr-opts');
  const syncTrOpts = () => trOpts.classList.toggle('hidden', !$('#tg-translate').classList.contains('on'));
  $('#tg-translate').addEventListener('click', syncTrOpts);
  $('#tg-translate').addEventListener('keydown', syncTrOpts);
  syncTrOpts();

  // painel de export KDP da aba Traduzir
  const trExpOpts = $('#tr-export-opts');
  const syncTrExpOpts = () => trExpOpts.classList.toggle('hidden', !$('#tg-tr-export').classList.contains('on'));
  $('#tg-tr-export').addEventListener('click', syncTrExpOpts);
  $('#tg-tr-export').addEventListener('keydown', syncTrExpOpts);
  syncTrExpOpts();

  // formato
  $$('#conv-format .fmt-btn').forEach(b => b.addEventListener('click', () => {
    convState.format = b.dataset.fmt;
    $$('#conv-format .fmt-btn').forEach(x => x.className = 'fmt-btn px-3 py-2.5 rounded-xl text-sm font-bold border border-white/10 glass text-slate-300');
    b.className = 'fmt-btn px-3 py-2.5 rounded-xl text-sm font-bold border border-violet-400/60 bg-violet-500/20';
  }));

  function progressBar(barSel, pctSel, msgSel, pct, msg) {
    $(barSel).style.width = pct + '%';
    $(pctSel).textContent = Math.round(pct) + '%';
    if (msgSel && msg) $(msgSel).textContent = msg;
  }

  $('#btn-convert').addEventListener('click', async () => {
    convState.title = $('#conv-title').value.trim();
    convState.author = $('#conv-author').value.trim();
    if (!convState.file) { toast('Selecione um <strong>PDF</strong> primeiro (ou use o exemplo).', 'err'); return; }
    const traduzir = $('#tg-translate').classList.contains('on');
    if (traduzir && $('#conv-tr-from').value === $('#conv-tr-to').value) {
      toast('Escolha idiomas de <strong>origem</strong> e <strong>destino</strong> diferentes.', 'err');
      return;
    }
    const prog = $('#convert-progress'); prog.classList.remove('hidden');
    const btn = $('#btn-convert'); btn.disabled = true;
    try {
      if (apiOnline) {
        progressBar('#convert-bar', '#convert-pct', '#convert-msg', 15, 'Enviando PDF…');
        const fd = new FormData();
        fd.append('file', convState.file);
        fd.append('remove_header', $('#tg-header').classList.contains('on'));
        fd.append('remove_page_numbers', $('#tg-pagenum').classList.contains('on'));
        fd.append('translate', traduzir);
        if (traduzir) {
          fd.append('source_lang', $('#conv-tr-from').value);
          fd.append('target_lang', $('#conv-tr-to').value);
          if ($('#conv-tr-model').value) fd.append('translation_model', $('#conv-tr-model').value);
        }
        fd.append('title', convState.title);
        fd.append('author', convState.author);
        fd.append('format', convState.format);
        progressBar('#convert-bar', '#convert-pct', '#convert-msg', 45, 'Convertendo no servidor…');
        const data = await apiFetch('/api/convert', { method: 'POST', body: fd });
        convState.jobId = data.job_id || data.id || null;
        convState.chapters = normalizeChapters(data.chapters || data.capitulos || []);
        progressBar('#convert-bar', '#convert-pct', '#convert-msg', 100, 'Concluído!');
        const extra = data.translated
          ? ' Traduzido para <strong>' + (data.target_lang || 'pt-BR') + '</strong>.'
          : '';
        toast('Conversão concluída: <strong>' + convState.chapters.length + ' capítulos</strong>.' + extra, 'ok');
      } else {
        // modo demo com progresso simulado
        for (let p = 5; p <= 100; p += 15) {
          progressBar('#convert-bar', '#convert-pct', '#convert-msg', p, p < 60 ? 'Lendo páginas…' : p < 90 ? 'Detectando capítulos…' : 'Finalizando…');
          await sleep(220);
        }
        convState.chapters = demoChapters(convState.title, convState.file.name);
        convState.jobId = 'demo-' + Date.now();
        toast('Modo demonstração: prévia simulada com <strong>' + convState.chapters.length + ' capítulos</strong>.' + ($('#tg-translate').classList.contains('on') ? ' tradução simulada (pt-BR)' : ''), 'info');
      }
      renderChapters();
    } catch (err) {
      console.error(err);
      // Erro do backend (ex.: 422 de PDF sem texto) não deve virar demo:
      // seria reportar sucesso sem converter. Mostra o motivo real.
      if (apiOnline && /^HTTP \d/.test(String(err && err.message))) {
        toast(escapeHtml(err.message), 'err');
        return;
      }
      toast('Falha na conversão. Tentando modo demonstração…', 'err');
      convState.chapters = demoChapters(convState.title, convState.file.name);
      convState.jobId = 'demo-' + Date.now();
      renderChapters();
    } finally {
      btn.disabled = false;
      setTimeout(() => prog.classList.add('hidden'), 1200);
    }
  });

  $('#btn-demo-convert').addEventListener('click', () => {
    $('#conv-title').value = $('#conv-title').value || 'O Segredo do Vale';
    $('#conv-author').value = $('#conv-author').value || 'Maria Silva';
    convState.title = $('#conv-title').value; convState.author = $('#conv-author').value;
    convState.chapters = demoChapters(convState.title, 'exemplo.pdf');
    convState.jobId = 'demo-' + Date.now();
    renderChapters();
    toast('Exemplo carregado: <strong>' + convState.chapters.length + ' capítulos</strong>.', 'ok');
  });

  function normalizeChapters(list) {
    return list.map((c, i) => ({
      title: c.title || c.titulo || ('Capítulo ' + (i + 1)),
      body: c.body || c.texto || c.preview || 'Sem prévia disponível.',
      words: c.words || c.palavras || (c.body || '').split(/\s+/).length,
      included: c.included !== false
    }));
  }

  function demoChapters(title, fname) {
    const t = title || 'O Segredo do Vale';
    const base = [
      ['Prólogo — A Carta', 'A adega cheirava a carvalho e tempo. Helena segurou a carta amarelada com as pontas dos dedos, como se o papel pudesse se desfazer entre um suspiro e outro. "Minha querida neta, há verdades que o vinho guarda melhor que os homens…". Lá fora, as vinhas do Douro ondulavam sob o vento de outubro, e um sino distante marcava cinco horas.'],
      ['Capítulo 1 — A Herança', 'O cartório era menor do que ela lembrava. O tabelião empurrou os óculos para a ponta do nariz e leu o testamento em voz monocórdica, mas cada palavra caía como uma pedra no copo d’água daquela manhã. A quinta, as dívidas, o nome da família — tudo agora pesava sobre os ombros de Helena.'],
      ['Capítulo 2 — O Enólogo Rival', 'Rafael chegou numa caminhonete empoeirada, sorriso fácil e olhar de quem já mediu cada fileira de videiras antes de dizer bom dia. "Você não vai conseguir sozinha", ele disse. Helena sorriu de volta: "Observe-me". O duelo estava lançado — e o prêmio era a safra do século.'],
      ['Capítulo 3 — O Porão Secreto', 'Atrás das pipas de 1962, uma porta que não constava em nenhuma planta. A lanterna tremeu na mão dela quando a luz revelou pilhas de cartas, fotografias e um diário de couro com as iniciais A.V. O passado da família, enfim, começava a fermentar.'],
      ['Capítulo 4 — Colheita e Confissão', 'Na madrugada da vindima, entre cestos de uvas e mãos manchadas de mosto, a verdade veio à tona como borbulhas num espumante: o incêndio de 1974 não fora acidente. E o nome do culpado estava escrito na última página do diário.'],
      ['Epílogo — A Nova Safra', 'Um ano depois, o rótulo novo brilhava na garrafa: "' + t + ' — Reserva". Helena ergueu a taça contra a luz dourada do pôr do sol. Algumas histórias, descobriu ela, precisam apenas do tempo certo para respirar.']
    ];
    return base.map(([title, body], i) => ({ title, body, words: body.split(/\s+/).length, included: true, demo: true, src: fname }));
  }

  function renderChapters() {
    const list = $('#chapters-list'), empty = $('#chapters-empty');
    if (!convState.chapters.length) { list.classList.add('hidden'); empty.classList.remove('hidden'); return; }
    empty.classList.add('hidden'); list.classList.remove('hidden');
    list.innerHTML = '';
    convState.chapters.forEach((c, i) => {
      const row = document.createElement('div');
      row.className = 'chapter-row flex items-center gap-3 rounded-xl px-3 py-2.5 border border-white/10 bg-white/[.03]' + (c.included ? '' : ' excluded');
      row.innerHTML = `
        <span class="w-8 h-8 rounded-lg grid place-items-center text-xs font-extrabold shrink-0" style="background:linear-gradient(135deg,#6366f1,#a855f7)">${i + 1}</span>
        <button class="flex-1 text-left min-w-0" data-act="open">
          <span class="block text-sm font-bold truncate">${escapeHtml(c.title)}</span>
          <span class="block text-[11px] text-slate-400">${(c.words || 0)} palavras · clique para ler</span>
        </button>
        <span class="toggle ${c.included ? 'on' : ''}" role="switch" aria-checked="${c.included}" title="Incluir/excluir da exportação" data-act="toggle" tabindex="0"></span>`;
      row.addEventListener('click', e => {
        const act = e.target.closest('[data-act]')?.dataset.act || 'open';
        if (act === 'toggle') { c.included = !c.included; renderChapters(); updateReader(c); }
        else updateReader(c);
      });
      list.appendChild(row);
    });
    updateReader(convState.chapters.find(c => c.included) || convState.chapters[0]);
    const n = convState.chapters.filter(c => c.included).length;
    const words = convState.chapters.filter(c => c.included).reduce((a, c) => a + (c.words || 0), 0);
    const stats = $('#convert-stats');
    stats.classList.remove('hidden');
    stats.innerHTML = `
      <div class="glass rounded-xl py-2"><p class="font-extrabold text-base">${convState.chapters.length}</p><p class="text-slate-400">capítulos</p></div>
      <div class="glass rounded-xl py-2"><p class="font-extrabold text-base">${n}</p><p class="text-slate-400">incluídos</p></div>
      <div class="glass rounded-xl py-2"><p class="font-extrabold text-base">${words.toLocaleString('pt-BR')}</p><p class="text-slate-400">palavras</p></div>`;
    $('#btn-dl-epub').disabled = $('#btn-dl-docx').disabled = false;
    saveToLibrary({ kind: 'Conversão', title: convState.title || 'Documento convertido', detail: n + ' capítulos · ' + words.toLocaleString('pt-BR') + ' palavras', jobId: convState.jobId });
  }

  function updateReader(c) {
    if (!c) return;
    $('#reader').classList.remove('hidden');
    $('#reader-kicker').textContent = (convState.title || 'Prévia do documento') + ' · ' + (convState.author || 'Autor desconhecido');
    $('#reader-title').textContent = c.title;
    $('#reader-body').textContent = c.body;
  }

  async function downloadExport(fmt) {
    // Guarda o INDICE ORIGINAL de cada capitulo incluido: o backend filtra
    // por indice original, nao pela posicao na lista filtrada.
    const included = [];
    convState.chapters.forEach((c, i) => { if (c.included) included.push({ c, index: i }); });
    if (!included.length) { toast('Inclua ao menos um capítulo para exportar.', 'err'); return; }
    toast('Gerando <strong>' + fmt.toUpperCase() + '</strong> com ' + included.length + ' capítulos…', 'info');
    try {
      if (apiOnline && convState.jobId && !String(convState.jobId).startsWith('demo-')) {
        const include = included.map(x => x.index).join(',');
        const blob = await apiFetch(`/api/convert/${convState.jobId}/download?format=${fmt}&include=${include}`);
        triggerBlobDownload(blob, slug(convState.title || 'livro') + '.' + fmt);
      } else {
        // exportação local (demonstração): gera arquivo texto/HTML válido
        const content = exportLocal(included.map(x => x.c), fmt);
        triggerBlobDownload(content.blob, content.filename);
      }
      toast('Arquivo <strong>' + fmt.toUpperCase() + '</strong> baixado com sucesso!', 'ok');
    } catch (e) { console.error(e); toast('Não foi possível gerar o arquivo: ' + escapeHtml(e.message || e), 'err'); }
  }

  function exportLocal(chapters, fmt) {
    const title = convState.title || 'Documento convertido';
    if (fmt === 'docx') {
      // HTML compatível com Word (abre no Word/LibreOffice)
      const html = `<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word"><head><meta charset="utf-8"><title>${escapeHtml(title)}</title></head><body><h1>${escapeHtml(title)}</h1><p>Autor: ${escapeHtml(convState.author || '—')}</p>${chapters.map(c => `<h2>${escapeHtml(c.title)}</h2><p>${escapeHtml(c.body).replace(/\n/g, '<br>')}</p>`).join('')}</body></html>`;
      return { blob: new Blob(['\ufeff', html], { type: 'application/msword' }), filename: slug(title) + '.doc' };
    }
    const html = `<?xml version="1.0" encoding="utf-8"?><!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml"><head><title>${escapeHtml(title)}</title></head><body><h1>${escapeHtml(title)}</h1>${chapters.map(c => `<h2>${escapeHtml(c.title)}</h2><p>${escapeHtml(c.body)}</p>`).join('')}</body></html>`;
    return { blob: new Blob([html], { type: 'application/epub+zip' }), filename: slug(title) + '.epub.html' };
  }

  function triggerBlobDownload(blob, filename) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 800);
  }

  $('#btn-dl-epub').addEventListener('click', () => downloadExport('epub'));
  $('#btn-dl-docx').addEventListener('click', () => downloadExport('docx'));
  $('#btn-print').addEventListener('click', () => window.print());

  /* ============================================================
     ABA 2 — TRADUZIR
  ============================================================ */
  const trState = { result: '', jobId: null };
  $('#file-translate').addEventListener('change', async e => {
    const f = e.target.files[0]; if (!f) return;
    $('#tr-filename').textContent = f.name;
    if (f.name.endsWith('.txt') || f.name.endsWith('.md')) {
      $('#tr-input').value = (await f.text()).slice(0, 20000);
      toast('Arquivo <strong>' + escapeHtml(f.name) + '</strong> carregado.', 'ok');
    } else toast('Arquivo anexado: <strong>' + escapeHtml(f.name) + '</strong>. O texto será extraído no servidor.', 'info');
  });

  $('#btn-translate').addEventListener('click', async () => {
    const text = $('#tr-input').value.trim();
    const from = $('#tr-from').value, to = $('#tr-to').value, model = $('#tr-model').value;
    if (!text && !$('#file-translate').files[0]) { toast('Cole um texto ou anexe um arquivo.', 'err'); return; }
    if (from === to) { toast('Os idiomas de origem e destino são iguais.', 'err'); return; }
    const exportar = $('#tg-tr-export').classList.contains('on');
    const prog = $('#tr-progress'); prog.classList.remove('hidden');
    const btn = $('#btn-translate'); btn.disabled = true; btn.classList.add('opacity-60');
    try {
      if (apiOnline) {
        progressBar('#tr-bar', '#tr-pct', '#tr-msg', 20, 'Enviando para ' + model + '…');
        const fd = new FormData();
        fd.append('text', text);
        if ($('#file-translate').files[0]) fd.append('file', $('#file-translate').files[0]);
        fd.append('source_lang', from); fd.append('target_lang', to);
        fd.append('model', model); fd.append('preserve_style', $('#tr-keep').checked);
        if (exportar) {
          fd.append('export', 'true');
          fd.append('format', 'epub');
          fd.append('title', $('#tr-exp-title').value.trim() || 'Tradução');
          fd.append('author', $('#tr-exp-author').value.trim() || 'Autor');
        }
        const tick = setInterval(() => {
          const cur = parseFloat($('#tr-bar').style.width) || 20;
          if (cur < 92) progressBar('#tr-bar', '#tr-pct', '#tr-msg', cur + 3, 'Traduzindo com ' + model + '…');
        }, 400);
        const data = await apiFetch('/api/translate', { method: 'POST', body: fd });
        clearInterval(tick);
        showTranslation(text, data.translated_text || data.result || data.text || '', { model, from, to });
        trState.jobId = data.job_id || null;
        setExportEpub(data.epub || null);
        progressBar('#tr-bar', '#tr-pct', '#tr-msg', 100, 'Concluído!');
      } else {
        for (let p = 8; p <= 100; p += 12) {
          progressBar('#tr-bar', '#tr-pct', '#tr-msg', p, p < 55 ? 'Analisando estilo…' : p < 85 ? 'Traduzindo com ' + model + '…' : 'Revisando…');
          await sleep(240);
        }
        showTranslation(text, demoTranslate(text, to), { model, from, to, demo: true });
        setExportEpub(null);
      }
    } catch (e) {
      console.error(e);
      // 422 (ex.: PDF sem texto) e' resposta real do backend, não queda de
      // rede: não mascarar com tradução demonstrativa.
      if (apiOnline && /^HTTP \d/.test(String(e && e.message))) {
        setExportEpub(null);
        toast(escapeHtml(e.message), 'err');
        return;
      }
      showTranslation(text, demoTranslate(text, to), { model, from, to, demo: true });
      setExportEpub(null);
      toast('Backend indisponível — mostrando <strong>prévia demonstrativa</strong>.', 'info');
    } finally {
      btn.disabled = false; btn.classList.remove('opacity-60');
      setTimeout(() => prog.classList.add('hidden'), 1200);
    }
  });

  function demoTranslate(text, to) {
    const sample = text || 'A adega cheirava a carvalho e tempo. Helena segurou a carta com as pontas dos dedos, como se o passado pudesse se desfazer entre um suspiro e outro.';
    const prefix = { en: '[EN · demo] ', es: '[ES · demo] ', fr: '[FR · demo] ', de: '[DE · demo] ', it: '[IT · demo] ', 'pt-BR': '[PT-BR · demo] ' }[to] || '[demo] ';
    const dictEn = [['adega', 'cellar'], ['carvalho', 'oak'], ['tempo', 'time'], ['carta', 'letter'], ['passado', 'past'], ['suspiro', 'sigh'], ['vinho', 'wine'], ['noite', 'night'], ['coração', 'heart'], ['segredo', 'secret']];
    let out = sample;
    if (to === 'en') dictEn.forEach(([pt, en]) => { out = out.replace(new RegExp(pt, 'gi'), en); });
    return prefix + out + '\n\n— Tradução demonstrativa gerada localmente. Conecte o backend (/api/translate) para tradução completa com ' + $('#tr-model').value + '.';
  }

  function showTranslation(orig, out, meta) {
    $('#tr-empty').classList.add('hidden');
    $('#tr-result').classList.remove('hidden');
    $('#tr-orig').textContent = orig || '(texto enviado por arquivo)';
    const el = $('#tr-out'); el.textContent = '';
    $('#btn-tr-dl').disabled = false;
    trState.result = out;
    // efeito de digitação
    let i = 0;
    const timer = setInterval(() => {
      el.textContent = out.slice(0, i += 14);
      if (i >= out.length) { clearInterval(timer); el.textContent = out; }
    }, 18);
    const words = out.split(/\s+/).length;
    const st = $('#tr-stats');
    st.classList.remove('hidden');
    st.innerHTML = `🤖 <strong class="text-slate-200">${escapeHtml(meta.model)}</strong> · ${escapeHtml(meta.from)} → ${escapeHtml(meta.to)} · ${words.toLocaleString('pt-BR')} palavras${meta.demo ? ' · <span class="text-amber-300">prévia local (demo)</span>' : ' · <span class="text-emerald-300">via API</span>'}`;
    saveToLibrary({ kind: 'Tradução', title: 'Tradução ' + meta.from + ' → ' + meta.to, detail: words.toLocaleString('pt-BR') + ' palavras · ' + meta.model });
  }

  $('#btn-tr-copy').addEventListener('click', async () => {
    if (!trState.result) return;
    await navigator.clipboard.writeText(trState.result).catch(() => {});
    toast('Tradução <strong>copiada</strong>!', 'ok');
  });
  function setExportEpub(url) {
    trState.exportEpub = url || null;
    const b = $('#btn-tr-dl-epub');
    if (b) b.classList.toggle('hidden', !url);
  }

  $('#btn-tr-dl-epub').addEventListener('click', async () => {
    if (!trState.exportEpub) return;
    try {
      const blob = await apiFetch(trState.exportEpub);
      triggerBlobDownload(blob, trState.exportEpub.split('/').pop() || 'traducao.epub');
    } catch (e) { console.error(e); toast('Falha ao baixar o EPUB.', 'err'); }
  });

  $('#btn-tr-dl').addEventListener('click', () => {
    if (!trState.result) return;
    triggerBlobDownload(new Blob([trState.result], { type: 'text/plain;charset=utf-8' }), 'traducao-' + Date.now() + '.txt');
    toast('Tradução <strong>baixada</strong>.', 'ok');
  });

  /* ============================================================
     ABA 3 — CRIAR EBOOK (wizard 4 passos)
  ============================================================ */
  const wiz = { step: 1, outline: [], bookChapters: [], coverDataUrl: null };
  const GENRES = {};

  function setStep(n) {
    wiz.step = Math.min(4, Math.max(1, n));
    $$('#stepper .step-item').forEach(li => {
      const s = +li.dataset.step;
      li.classList.toggle('done', s < wiz.step);
      li.classList.toggle('current', s === wiz.step);
      li.querySelector('.step-dot').innerHTML = s < wiz.step ? '✓' : ['💡', '🎯', '🗂', '📖'][s - 1];
    });
    $$('.wizard-pane').forEach(p => p.classList.toggle('hidden', +p.dataset.pane !== wiz.step));
    $('#wiz-back').disabled = wiz.step === 1;
    $('#wiz-next').textContent = wiz.step === 4 ? '🎉 Finalizar livro' : 'Continuar →';
    if (wiz.step === 2) updateScopePreview();
  }
  $('#wiz-back').addEventListener('click', () => setStep(wiz.step - 1));
  $('#wiz-next').addEventListener('click', () => {
    if (wiz.step === 1 && !$('#bk-idea').value.trim()) { toast('Descreva sua <strong>ideia</strong> primeiro. 💡', 'err'); return; }
    if (wiz.step === 3 && !wiz.outline.length) { toast('Gere o <strong>roteiro</strong> antes de avançar. 🗂', 'err'); return; }
    if (wiz.step === 4) { finalizeBook(); return; }
    setStep(wiz.step + 1);
  });

  $$('.idea-chip').forEach(c => c.addEventListener('click', () => {
    $('#bk-idea').value = 'Escreva ' + c.textContent.trim().charAt(0).toLowerCase() + c.textContent.trim().slice(1) + ', com reviravoltas e final emocionante.';
    toast('Ideia aplicada — personalize à vontade! ✨', 'ok');
  }));
  $('#btn-demo-book').addEventListener('click', () => {
    $('#bk-idea').value = 'Um romance de mistério numa vinícola no Douro: a enóloga Helena herda a quinta da família e descobre cartas que revelam um incêndio criminoso em 1974. Com a ajuda (e a rivalidade) do enólogo Rafael, ela precisa salvar a safra do século e expor o culpado.';
    $('#bk-genre').value = 'Mistério / Thriller'; $('#bk-style').value = 'Literário e envolvente';
    $('#bk-audience').value = 'Adultos (30–50)'; $('#bk-size').value = '12';
    $('#bk-title').value = 'O Segredo do Vale'; $('#bk-author').value = 'Maria Silva';
    $('#bk-cover-prompt').value = 'Vinícola no Douro ao pôr do sol, fileiras de vinhas, adega de pedra, estilo cinematográfico';
    updateCoverMock(); setStep(1);
    toast('Exemplo de <strong>romance de mistério</strong> carregado! Clique em Continuar. ✨', 'ok');
  });

  ['#bk-genre', '#bk-style', '#bk-audience', '#bk-size', '#bk-title', '#bk-author'].forEach(sel => {
    $(sel).addEventListener('input', updateScopePreview);
    $(sel).addEventListener('change', updateScopePreview);
  });
  function scope() {
    return {
      idea: $('#bk-idea').value.trim(), genre: $('#bk-genre').value, style: $('#bk-style').value,
      audience: $('#bk-audience').value, size: +$('#bk-size').value || 12,
      title: $('#bk-title').value.trim() || 'Meu eBook', author: $('#bk-author').value.trim() || 'Autor Independente'
    };
  }
  function updateScopePreview() {
    const s = scope();
    $('#scope-preview').innerHTML = `<strong class="text-white">“${escapeHtml(s.title)}”</strong> · ${escapeHtml(s.genre)} · ${escapeHtml(s.style.toLowerCase())} · para ${escapeHtml(s.audience.toLowerCase())} · <strong class="text-violet-200">${s.size} capítulos</strong>${s.idea ? '<br><span class="text-slate-400">Ideia: ' + escapeHtml(s.idea.slice(0, 160)) + (s.idea.length > 160 ? '…' : '') + '</span>' : ''}`;
    updateCoverMock();
  }

  // ---- roteiro ----
  $('#btn-gen-outline').addEventListener('click', async () => {
    const s = scope();
    if (!s.idea) { toast('Volte ao passo 1 e descreva a <strong>ideia</strong>.', 'err'); setStep(1); return; }
    $('#outline-progress').classList.remove('hidden');
    try {
      if (apiOnline) {
        const data = await apiFetch('/api/ebook/outline', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ idea: s.idea, genre: s.genre, style: s.style, audience: s.audience, num_chapters: s.size, title: s.title })
        });
        wiz.outline = (data.outline || data.chapters || []).map((c, i) => typeof c === 'string' ? { title: c, synopsis: '' } : { title: c.title || c.titulo || ('Capítulo ' + (i + 1)), synopsis: c.synopsis || c.sinopse || c.summary || '' });
      } else {
        await sleep(900);
        wiz.outline = demoOutline(s);
      }
      renderOutline();
      toast('Roteiro com <strong>' + wiz.outline.length + ' capítulos</strong> pronto! Edite à vontade. 🗂', 'ok');
    } catch (e) { console.error(e); wiz.outline = demoOutline(s); renderOutline(); toast('Backend indisponível — roteiro <strong>demonstrativo</strong> gerado.', 'info'); }
    finally { $('#outline-progress').classList.add('hidden'); }
  });

  function demoOutline(s) {
    const arcs = [
      ['O Ponto de Partida', 'Apresenta a protagonista, o cenário e o desejo central. Termina com o evento que tira tudo do lugar.'],
      ['A Herança Inesperada', 'Um documento, uma morte ou uma carta muda o destino. Novos aliados e o primeiro obstáculo.'],
      ['O Rival', 'Surge quem disputa o mesmo objetivo — tensão, faíscas e uma aliança improvável.'],
      ['Pistas e Suspeitas', 'Descobertas que reviram a história oficial. Um segredo vem à tona pela metade.'],
      ['O Porão / O Arquivo', 'O esconderijo: cartas, diários, provas. O mistério ganha nome e rosto.'],
      ['Reviravolta', 'Quem parecia aliado trai; quem parecia vilão ajuda. O plano desmorona.'],
      ['A Noite Mais Longa', 'Tudo dá errado na véspera do clímax. A protagonista quase desiste.'],
      ['Colheita / Confronto', 'O embate final: verdade revelada em público, justiça e catarse.'],
      ['O Preço da Verdade', 'Consequências emocionais. Perdas, perdão e reconciliação.'],
      ['Nova Safra', 'Um ano depois: o recomeço. Gancho sutil para o próximo livro.']
    ];
    const out = [];
    for (let i = 0; i < s.size; i++) {
      const a = arcs[i % arcs.length];
      out.push({ title: `Capítulo ${i + 1} — ${i < arcs.length ? a[0] : a[0] + ' (parte ' + (Math.floor(i / arcs.length) + 1) + ')'}`, synopsis: a[1] });
    }
    return out;
  }

  function renderOutline() {
    const box = $('#outline-list'); box.innerHTML = '';
    if (!wiz.outline.length) { box.innerHTML = '<p class="text-sm text-slate-500 text-center py-6">Clique em “Gerar roteiro com IA” para começar. 🤖</p>'; return; }
    wiz.outline.forEach((ch, i) => {
      const el = document.createElement('div');
      el.className = 'glass rounded-2xl p-3 flex gap-3 items-start anim-fadeIn';
      el.innerHTML = `
        <span class="w-8 h-8 rounded-lg grid place-items-center text-xs font-extrabold shrink-0 mt-0.5" style="background:linear-gradient(135deg,#6366f1,#a855f7)">${i + 1}</span>
        <div class="flex-1 min-w-0">
          <input value="${escapeAttr(ch.title)}" data-k="title" class="field w-full px-3 py-2 text-sm font-bold" placeholder="Título do capítulo">
          <textarea data-k="synopsis" rows="2" class="field w-full mt-1.5 px-3 py-2 text-xs" placeholder="Sinopse do capítulo…">${escapeHtml(ch.synopsis || '')}</textarea>
        </div>
        <div class="flex flex-col gap-1 shrink-0">
          <button data-a="up" class="w-8 h-8 rounded-lg glass text-sm hover:bg-white/10" title="Mover para cima">↑</button>
          <button data-a="down" class="w-8 h-8 rounded-lg glass text-sm hover:bg-white/10" title="Mover para baixo">↓</button>
          <button data-a="del" class="w-8 h-8 rounded-lg text-sm bg-rose-500/15 border border-rose-400/30 hover:bg-rose-500/30" title="Remover">✕</button>
        </div>`;
      el.querySelector('[data-k="title"]').addEventListener('input', e => ch.title = e.target.value);
      el.querySelector('[data-k="synopsis"]').addEventListener('input', e => ch.synopsis = e.target.value);
      el.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
        if (b.dataset.a === 'del' && wiz.outline.length > 1) wiz.outline.splice(i, 1);
        if (b.dataset.a === 'up' && i > 0) [wiz.outline[i - 1], wiz.outline[i]] = [wiz.outline[i], wiz.outline[i - 1]];
        if (b.dataset.a === 'down' && i < wiz.outline.length - 1) [wiz.outline[i + 1], wiz.outline[i]] = [wiz.outline[i], wiz.outline[i + 1]];
        renderOutline();
      }));
      box.appendChild(el);
    });
  }
  $('#btn-add-ch').addEventListener('click', () => {
    wiz.outline.push({ title: `Capítulo ${wiz.outline.length + 1} — Novo capítulo`, synopsis: '' });
    renderOutline();
  });

  // ---- capítulos ----
  $('#btn-gen-chapters').addEventListener('click', async () => {
    const s = scope();
    if (!wiz.outline.length) { toast('Gere o <strong>roteiro</strong> primeiro (passo 3).', 'err'); setStep(3); return; }
    const prog = $('#book-progress'); prog.classList.remove('hidden');
    wiz.bookChapters = [];
    let usadoMock = false;
    renderBookChapters();
    try {
      for (let i = 0; i < wiz.outline.length; i++) {
        const ch = wiz.outline[i];
        progressBar('#book-bar', '#book-pct', '#book-msg', (i / wiz.outline.length) * 100, `Escrevendo ${i + 1}/${wiz.outline.length}: ${ch.title.slice(0, 40)}…`);
        let body = '';
        if (apiOnline) {
          try {
            const data = await apiFetch('/api/ebook/chapter', {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ title: s.title, author: s.author, genre: s.genre, style: s.style, chapter_title: ch.title, chapter_synopsis: ch.synopsis, chapter_number: i + 1, idea: s.idea })
            });
            body = data.text || data.body || data.content || '';
            if (data.mock) usadoMock = true;
          } catch { body = ''; }
        }
        if (!body) { await sleep(350); body = demoChapterBody(s, ch, i); usadoMock = true; }
        wiz.bookChapters.push({ title: ch.title, body, words: body.split(/\s+/).length });
        renderBookChapters();
      }
      progressBar('#book-bar', '#book-pct', '#book-msg', 100, 'Livro pronto! 🎉');
      toast('Manuscrito pronto: <strong>' + wiz.bookChapters.length + ' capítulos</strong> escritos!', 'ok');
      if (usadoMock) toast('Parte do texto veio do <strong>fallback local</strong> (IA indisponível ou chave ausente). Revise antes de publicar.', 'info');
      $('#btn-book-epub').disabled = $('#btn-book-docx').disabled = false;
    } catch (e) { console.error(e); toast('Erro ao gerar capítulos.', 'err'); }
    finally { setTimeout(() => prog.classList.add('hidden'), 1500); }
  });

  function demoChapterBody(s, ch, i) {
    const openers = [
      'A manhã chegou com cheiro de possibilidade, e nada seria como antes.',
      'Havia um silêncio estranho no ar — daqueles que antecedem revelações.',
      'Dizem que toda história de família esconde uma porta trancada. Naquela tarde, a porta se abriu.',
      'O relógio da torre marcou seis badaladas quando tudo mudou de figura.'
    ];
    return `${openers[i % openers.length]}\n\n${ch.synopsis || 'A trama avança, e as peças do quebra-cabeça começam a se encaixar.'}\n\nO cenário — ${s.genre.toLowerCase()} em estado puro — ganhava vida a cada detalhe: sons, cheiros, o peso do passado pressionando o presente. A escrita ${s.style.toLowerCase()} conduzia o leitor sem pressa, mas sem trégua, até que um diálogo cortante virou a cena do avesso.\n\n— Você não sabe a metade — disse a voz, firme, do outro lado da porta.\n\nE, de repente, o capítulo terminava num gancho impossível de largar: uma revelação a meio caminho entre o alívio e o perigo. O próximo capítulo prometia respostas — ou perguntas ainda maiores.\n\n[Texto demonstrativo gerado localmente. Conecte o backend para capítulos completos via IA.]`;
  }

  // Abre o leitor do capítulo E registra o handler de edição. Antes o branch
  // de auto-abertura nao registrava oninput, entao a edicao era perdida.
  function openBookReader(c, scroll) {
    if (!c) return;
    const body = $('#book-reader-body');
    $('#book-reader').classList.remove('hidden');
    $('#book-reader-title').textContent = c.title;
    body.textContent = c.body || '';
    body.oninput = () => {
      c.body = body.textContent;
      const t = (c.body || '').trim();
      c.words = t ? t.split(/\s+/).length : 0;
    };
    if (scroll) $('#book-reader').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function renderBookChapters() {
    const box = $('#book-chapters'); box.innerHTML = '';
    if (!wiz.bookChapters.length) { box.innerHTML = '<p class="text-sm text-slate-500 text-center py-8">Os capítulos gerados aparecem aqui. Clique para ler e editar.</p>'; return; }
    wiz.bookChapters.forEach((c, i) => {
      const row = document.createElement('button');
      row.className = 'chapter-row w-full text-left flex items-center gap-3 rounded-xl px-3 py-2.5 border border-white/10 bg-white/[.03]';
      row.innerHTML = `<span class="w-8 h-8 rounded-lg grid place-items-center text-xs font-extrabold shrink-0" style="background:linear-gradient(135deg,#10b981,#0ea5e9)">${i + 1}</span>
        <span class="flex-1 min-w-0"><span class="block text-sm font-bold truncate">${escapeHtml(c.title)}</span><span class="block text-[11px] text-slate-400">${c.words.toLocaleString('pt-BR')} palavras</span></span><span class="text-slate-500">→</span>`;
      row.addEventListener('click', () => openBookReader(c, true));
      box.appendChild(row);
    });
    if (wiz.bookChapters.length && $('#book-reader').classList.contains('hidden')) {
      openBookReader(wiz.bookChapters[0], false);
    }
  }

  // ---- capa ----
  function updateCoverMock() {
    $('#cover-title').textContent = $('#bk-title').value.trim() || 'Seu título aqui';
    $('#cover-author').textContent = ($('#bk-author').value.trim() || 'Autor').toUpperCase();
  }
  ['#bk-title', '#bk-author'].forEach(s => $(s).addEventListener('input', updateCoverMock));
  $('#btn-gen-cover').addEventListener('click', async () => {
    const prompt = $('#bk-cover-prompt').value.trim() || scope().title + ', ' + scope().genre;
    toast('Gerando capa… 🎨', 'info');
    try {
      if (apiOnline) {
        const data = await apiFetch('/api/ebook/cover', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prompt, title: scope().title, author: scope().author })
        });
        const url = data.image_url || data.url;
        if (url) {
          $('#cover-box').innerHTML = `<img src="${escapeAttr(url)}" alt="Capa do livro" class="w-full h-full object-cover rounded-xl">`;
          toast('Capa gerada com sucesso! 🎨', 'ok');
          return;
        }
        throw new Error('sem url');
      } else {
        await sleep(700);
        // capa procedural: gradiente + tipografia (demo)
        const palettes = [
          ['#1e1b4b', '#6d28d9', '#b45309'], ['#0c4a6e', '#0ea5e9', '#f59e0b'],
          ['#3b0764', '#a855f7', '#ec4899'], ['#052e16', '#059669', '#a3e635']
        ];
        const p = palettes[scope().title.length % palettes.length];
        $('#cover-box').style.background = `linear-gradient(160deg,${p[0]},${p[1]} 55%,${p[2]})`;
        updateCoverMock();
        toast('Capa demonstrativa aplicada. Conecte o backend para arte com IA. 🎨', 'info');
      }
    } catch (e) { console.error(e); toast('Não foi possível gerar a capa.', 'err'); }
  });

  async function bookExport(fmt) {
    if (!wiz.bookChapters.length) { toast('Gere os capítulos primeiro. ✍️', 'err'); return; }
    const s = scope();
    toast('Gerando ' + fmt.toUpperCase() + ' de <strong>' + escapeHtml(s.title) + '</strong>…', 'info');
    try {
      if (apiOnline) {
        const blob = await apiFetch('/api/ebook/export', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: s.title, author: s.author, format: fmt, chapters: wiz.bookChapters })
        });
        triggerBlobDownload(blob, slug(s.title) + '.' + fmt);
      } else {
        const html = `<html><head><meta charset="utf-8"><title>${escapeHtml(s.title)}</title></head><body><h1>${escapeHtml(s.title)}</h1><p>${escapeHtml(s.author)}</p>${wiz.bookChapters.map(c => `<h2>${escapeHtml(c.title)}</h2><p>${escapeHtml(c.body).replace(/\n/g, '<br>')}</p>`).join('')}</body></html>`;
        triggerBlobDownload(new Blob(['\ufeff', html], { type: fmt === 'docx' ? 'application/msword' : 'text/html' }), slug(s.title) + (fmt === 'docx' ? '.doc' : '.epub.html'));
      }
      toast('Arquivo <strong>' + fmt.toUpperCase() + '</strong> baixado!', 'ok');
      saveToLibrary({ kind: 'eBook IA', title: s.title, detail: wiz.bookChapters.length + ' capítulos · ' + s.genre });
    } catch (e) { console.error(e); toast('Falha na exportação.', 'err'); }
  }
  $('#btn-book-epub').addEventListener('click', () => bookExport('epub'));
  $('#btn-book-docx').addEventListener('click', () => bookExport('docx'));

  function finalizeBook() {
    if (!wiz.bookChapters.length) { toast('Gere os <strong>capítulos</strong> antes de finalizar. ✍️', 'err'); return; }
    const s = scope();
    saveToLibrary({ kind: 'eBook IA', title: s.title, detail: wiz.bookChapters.length + ' capítulos · ' + s.genre + ' · ' + s.author });
    toast('🎉 Livro <strong>' + escapeHtml(s.title) + '</strong> finalizado e salvo na Biblioteca!', 'ok');
    $$('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === 'library'));
    $$('.tab-panel').forEach(p => p.classList.remove('active'));
    $('#tab-library').classList.add('active');
    renderLibrary();
  }
  $('#btn-save-lib').addEventListener('click', () => {
    if (!wiz.bookChapters.length && !wiz.outline.length) { toast('Nada para salvar ainda.', 'err'); return; }
    const s = scope();
    saveToLibrary({ kind: 'eBook IA', title: s.title, detail: (wiz.bookChapters.length || wiz.outline.length) + ' capítulos · ' + s.genre });
    toast('Projeto salvo na <strong>Biblioteca</strong>. 💾', 'ok');
  });

  /* ============================================================
     ABA 4 — BIBLIOTECA
  ============================================================ */
  const LS_KEY = 'kdp-studio-library';
  function getLocal() { try { return JSON.parse(localStorage.getItem(LS_KEY) || '[]'); } catch { return []; } }
  function setLocal(v) { localStorage.setItem(LS_KEY, JSON.stringify(v.slice(0, 60))); }
  function saveToLibrary(item) {
    const lib = getLocal();
    lib.unshift({ id: 'lib-' + Date.now(), date: new Date().toLocaleString('pt-BR'), ...item });
    setLocal(lib);
    if ($('#tab-library').classList.contains('active')) renderLibrary();
  }

  async function renderLibrary() {
    const grid = $('#lib-grid'), empty = $('#lib-empty');
    let items = getLocal();
    if (apiOnline) {
      try {
        const data = await apiFetch('/api/library');
        const remote = data.items || data.outputs || data || [];
        if (Array.isArray(remote) && remote.length) {
          items = remote.map((r, i) => ({
            id: r.id || 'srv-' + i,
            kind: r.kind || r.type || 'Arquivo',
            title: r.title || r.name || 'Sem título',
            detail: r.detail || r.description || '',
            date: r.created_at || r.date || '',
            download: r.download_url || null,
            scope: 'server'
          })).concat(items);
        }
      } catch { /* mantém local */ }
    }
    const q = ($('#lib-search').value || '').toLowerCase();
    const filtered = items.filter(it => (it.title + ' ' + it.kind).toLowerCase().includes(q));
    grid.innerHTML = '';
    empty.style.display = filtered.length ? 'none' : '';
    const icons = { 'Conversão': '📄', 'Tradução': '🌍', 'eBook IA': '✨' };
    filtered.forEach(it => {
      const card = document.createElement('div');
      card.className = 'glass rounded-2xl p-4 card-hover anim-fadeIn';
      card.innerHTML = `
        <div class="flex items-start justify-between gap-2">
          <span class="text-3xl">${icons[it.kind] || '📕'}</span>
          <span class="text-[10px] font-extrabold px-2 py-1 rounded-full bg-violet-500/20 border border-violet-400/40 text-violet-200">${escapeHtml(it.kind || 'Arquivo')}</span>
        </div>
        <p class="font-bold mt-2 leading-snug">${escapeHtml(it.title)}</p>
        <p class="text-xs text-slate-400 mt-0.5">${escapeHtml(it.detail || '')}</p>
        <p class="text-[11px] text-slate-500 mt-1">🕒 ${escapeHtml(it.date || '')}</p>
        <div class="flex gap-2 mt-3">
          ${it.download ? `<a href="${escapeAttr(it.download)}" class="flex-1 text-center px-3 py-2 rounded-xl text-xs font-bold bg-emerald-500/20 border border-emerald-400/40 text-emerald-200">⬇ Baixar</a>` : ''}
          <button data-del class="px-3 py-2 rounded-xl text-xs font-bold bg-rose-500/15 border border-rose-400/30 hover:bg-rose-500/30 transition">🗑</button>
        </div>`;
      card.querySelector('[data-del]').addEventListener('click', async () => {
        const alvo = it.scope === 'server' ? ' do servidor' : '';
        if (!window.confirm('Remover "' + it.title + '"' + alvo + '?')) return;
        if (it.scope === 'server' && apiOnline) {
          // Apaga o arquivo de verdade: antes so saia do localStorage e o
          // item reaparecia no proximo refresh.
          try {
            await apiFetch('/api/library/' + encodeURIComponent(it.id), { method: 'DELETE' });
          } catch (e) {
            console.error(e);
            toast('Não foi possível remover o arquivo: ' + escapeHtml(e.message || e), 'err');
            return;
          }
        } else {
          setLocal(getLocal().filter(x => x.id !== it.id));
        }
        renderLibrary();
        toast('Item removido da Biblioteca.', 'info');
      });
      grid.appendChild(card);
    });
  }
  $('#btn-lib-refresh').addEventListener('click', () => { renderLibrary(); toast('Biblioteca atualizada. 📚', 'ok'); });
  $('#lib-search').addEventListener('input', renderLibrary);

  /* ---------- utils ---------- */
  function escapeHtml(s) { return String(s ?? '').replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m])); }
  function escapeAttr(s) { return escapeHtml(s).replace(/"/g, '&quot;'); }
  function slug(s) { return (s || 'livro').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'livro'; }
  function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

  /* ---------- init ---------- */
  setStep(1);
  renderOutline();
  renderLibrary();
  (async () => {
    await checkApi();
    await loadApiInfo();
  })();
})();
