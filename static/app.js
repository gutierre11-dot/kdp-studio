/* KDP Studio — fluxo único em 3 passos: PDF -> (tradução) -> revisão -> EPUB.
   Sem fallback que simule sucesso: toda falha do servidor é mostrada como falha. */
(function () {
  'use strict';

  const $ = (sel, raiz) => (raiz || document).querySelector(sel);

  /* ---------- utilidades ---------- */
  function escapeHtml(valor) {
    return String(valor === null || valor === undefined ? '' : valor)
      .replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
  }
  function slug(texto) {
    return (texto || 'livro').toLowerCase().normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '') || 'livro';
  }
  function toast(mensagem, tipo) {
    const cores = { ok: 'border-emerald-400/40', err: 'border-rose-400/40', info: 'border-violet-400/40' };
    const icones = { ok: '✅', err: '⛔', info: '💡' };
    const el = document.createElement('div');
    el.className = 'toast glass rounded-2xl px-4 py-3 text-sm border ' +
      (cores[tipo] || cores.info) + ' flex gap-2 items-start shadow-xl';
    el.innerHTML = '<span>' + (icones[tipo] || icones.info) + '</span><span>' +
      escapeHtml(mensagem) + '</span>';
    const raiz = $('#toast-root');
    if (!raiz) return;
    raiz.appendChild(el);
    setTimeout(() => { el.classList.add('hide'); setTimeout(() => el.remove(), 320); }, 5000);
  }
  function ocupado(seletor, valor) {
    const el = $(seletor);
    if (el) el.setAttribute('aria-busy', valor ? 'true' : 'false');
  }
  function baixar(blob, nome) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = nome;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 800);
  }

  /* ---------- HTTP ---------- */
  async function api(caminho, opcoes) {
    const resposta = await fetch(caminho, opcoes);
    if (!resposta.ok) {
      let detalhe = '';
      try { detalhe = (await resposta.json()).detail || ''; } catch (_) { /* corpo não-JSON */ }
      throw new Error(detalhe || ('HTTP ' + resposta.status));
    }
    return resposta;
  }

  /* ---------- estado ---------- */
  const estado = { arquivo: null, jobId: null, capitulos: [], timer: null, online: false };

  /* ---------- status do servidor ---------- */
  function marcarOffline(motivo) {
    estado.online = false;
    const selo = $('#api-status');
    if (selo) {
      selo.innerHTML = '<span class="text-rose-400">●</span> Servidor offline';
      selo.title = motivo || 'O backend FastAPI não respondeu.';
    }
    $('#btn-start').disabled = true;
    desabilitarToggle('#tg-translate', 'Servidor offline.');
  }

  function desabilitarToggle(seletor, motivo) {
    const el = $(seletor);
    if (!el) return;
    el.setAttribute('aria-disabled', 'true');
    el.title = motivo;
    if (el.classList.contains('on')) {
      el.classList.remove('on');
      el.setAttribute('aria-checked', 'false');
    }
  }

  async function checkApi() {
    try {
      await api('/api/health');
      const cfg = await (await api('/api/config')).json();
      estado.online = true;
      const nomes = { openai: 'OpenAI', gemini: 'Gemini', offline: 'sem IA' };
      const selo = $('#api-status');
      selo.innerHTML = '<span class="text-emerald-400">●</span> Conectado · ' +
        escapeHtml(nomes[cfg.provider] || cfg.provider);
      selo.title = cfg.configured
        ? ('Modelo: ' + cfg.translation_model)
        : 'Sem chave de IA: a tradução fica indisponível.';
      $('#btn-start').disabled = false;

      const seletor = $('#tr-model');
      const opcoes = [];
      if (cfg.translation_model) opcoes.push(cfg.translation_model);
      (cfg.fallback_models || []).forEach(m => { if (opcoes.indexOf(m) === -1) opcoes.push(m); });
      seletor.innerHTML = '<option value="">Padrão do servidor</option>' +
        opcoes.map(m => '<option value="' + escapeHtml(m) + '">' + escapeHtml(m) + '</option>').join('');

      if (!cfg.configured) {
        desabilitarToggle('#tg-translate', 'Nenhuma chave de IA configurada no servidor.');
        $('#tr-opts').classList.add('hidden');
      }
    } catch (erro) {
      marcarOffline(erro.message);
    }
  }

  /* ---------- passos ---------- */
  function irParaPasso(n) {
    [1, 2, 3].forEach(i => $('#step-' + i).classList.toggle('hidden', i !== n));
    document.querySelectorAll('#stepper .step-item').forEach(item => {
      const passo = Number(item.dataset.step);
      item.classList.toggle('done', passo < n);
      item.classList.toggle('current', passo === n);
      item.querySelector('.step-dot').textContent = passo < n ? '✓' : ['📄', '⏳', '📖'][passo - 1];
    });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
  function progresso(pct, mensagem) {
    $('#progress-bar').style.width = Math.max(0, Math.min(100, pct)) + '%';
    $('#progress-pct').textContent = Math.round(pct) + '%';
    if (mensagem) $('#progress-msg').textContent = mensagem;
  }

  /* ---------- toggles ---------- */
  function ligarToggle(seletor, aoMudar) {
    const el = $(seletor);
    const alternar = () => {
      if (el.getAttribute('aria-disabled') === 'true') return;
      el.classList.toggle('on');
      el.setAttribute('aria-checked', el.classList.contains('on') ? 'true' : 'false');
      if (aoMudar) aoMudar();
    };
    el.addEventListener('click', alternar);
    el.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); alternar(); }
    });
  }
  const ligado = seletor => {
    const el = $(seletor);
    return !!el && el.classList.contains('on');
  };

  /* ---------- upload ---------- */
  const dz = $('#dz-file');
  const entrada = $('#file-input');
  dz.addEventListener('click', () => entrada.click());
  dz.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); entrada.click(); }
  });
  ['dragenter', 'dragover'].forEach(ev => dz.addEventListener(ev, e => {
    e.preventDefault(); dz.classList.add('drag-over');
  }));
  ['dragleave', 'drop'].forEach(ev => dz.addEventListener(ev, e => {
    e.preventDefault(); dz.classList.remove('drag-over');
  }));
  dz.addEventListener('drop', e => {
    const f = e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) definirArquivo(f);
  });
  entrada.addEventListener('change', () => {
    if (entrada.files[0]) definirArquivo(entrada.files[0]);
  });

  function definirArquivo(arquivo) {
    if (!/\.pdf$/i.test(arquivo.name) && arquivo.type !== 'application/pdf') {
      toast('Envie um arquivo PDF.', 'err');
      return;
    }
    estado.arquivo = arquivo;
    $('#file-name').textContent = '📎 ' + arquivo.name + ' (' +
      (arquivo.size / 1048576).toFixed(1) + ' MB)';
    const titulo = $('#inp-title');
    if (!titulo.value) titulo.value = arquivo.name.replace(/\.pdf$/i, '').replace(/[_-]+/g, ' ').trim();
    toast('PDF pronto para converter.', 'ok');
  }

  /* ---------- iniciar job ---------- */
  ligarToggle('#tg-header');
  ligarToggle('#tg-pagenum');
  ligarToggle('#tg-translate', () => {
    $('#tr-opts').classList.toggle('hidden', !ligado('#tg-translate'));
  });

  $('#btn-start').addEventListener('click', async () => {
    if (!estado.arquivo) { toast('Selecione um PDF primeiro.', 'err'); return; }
    if (!estado.online) { toast('O servidor não está respondendo.', 'err'); return; }

    const traduzir = ligado('#tg-translate');
    const origem = $('#tr-from').value;
    const destino = $('#tr-to').value;
    if (traduzir && origem !== 'auto' && origem === destino) {
      toast('Escolha idiomas de origem e destino diferentes.', 'err');
      return;
    }

    const dados = new FormData();
    dados.append('file', estado.arquivo);
    dados.append('title', $('#inp-title').value.trim() || 'Livro');
    dados.append('author', $('#inp-author').value.trim() || 'Autor');
    dados.append('remove_header', ligado('#tg-header'));
    dados.append('remove_page_numbers', ligado('#tg-pagenum'));
    dados.append('translate', traduzir);
    if (traduzir) {
      dados.append('source_lang', origem);
      dados.append('target_lang', destino);
      const modelo = $('#tr-model').value;
      if (modelo) dados.append('translation_model', modelo);
    }

    ocupado('#btn-start', true);
    irParaPasso(2);
    $('#status-msg').textContent = 'Enviando e lendo o PDF…';
    progresso(5, 'Enviando o PDF…');
    try {
      const resposta = await api('/api/jobs', { method: 'POST', body: dados });
      const corpo = await resposta.json();
      estado.jobId = corpo.job_id;
      acompanhar();
    } catch (erro) {
      toast(erro.message, 'err');
      irParaPasso(1);
    } finally {
      ocupado('#btn-start', false);
    }
  });

  /* ---------- acompanhar progresso ---------- */
  function pararTimer() {
    if (estado.timer) { clearInterval(estado.timer); estado.timer = null; }
  }

  function acompanhar() {
    pararTimer();
    estado.timer = setInterval(async () => {
      try {
        const job = await (await api('/api/jobs/' + estado.jobId)).json();
        progresso(job.progress, job.message || job.stage);
        $('#status-msg').textContent = job.stage || '';
        if (job.status === 'done') { pararTimer(); concluir(job); }
        else if (job.status === 'error') { pararTimer(); falhar(job.error || 'Falha ao processar o PDF.'); }
        else if (job.status === 'cancelled') { pararTimer(); falhar('Processamento cancelado.'); }
      } catch (erro) {
        pararTimer();
        falhar(erro.message);
      }
    }, 800);
  }

  function concluir(job) {
    estado.titulo = job.title;
    estado.idioma = job.language;
    estado.capitulos = (job.chapters || []).map(c => ({
      index: c.index, title: c.title, level: c.level,
      words: c.words, preview: c.preview, included: true,
    }));
    const avisos = job.warnings || [];
    const caixa = $('#warn-box');
    if (avisos.length) {
      caixa.classList.remove('hidden');
      caixa.innerHTML = '<strong>⚠️ Avisos</strong><ul class="mt-1 list-disc list-inside">' +
        avisos.map(a => '<li>' + escapeHtml(a) + '</li>').join('') + '</ul>';
    } else {
      caixa.classList.add('hidden');
    }
    renderizarCapitulos();
    irParaPasso(3);
    toast('Conversão concluída: ' + estado.capitulos.length + ' capítulos.', 'ok');
  }

  function falhar(mensagem) {
    $('#status-msg').textContent = '';
    toast(mensagem, 'err');
    irParaPasso(1);
  }

  /* ---------- lista de capítulos ---------- */
  function renderizarCapitulos() {
    const lista = $('#chapters-list');
    lista.innerHTML = '';
    estado.capitulos.forEach((cap, pos) => {
      const linha = document.createElement('div');
      linha.className = 'chapter-row rounded-xl px-3 py-2.5 border border-white/10 bg-white/[.03]' +
        (cap.included ? '' : ' excluded');
      linha.innerHTML =
        '<div class="flex items-center gap-2">' +
          '<span class="w-7 h-7 rounded-lg grid place-items-center text-[11px] font-extrabold shrink-0" style="background:linear-gradient(135deg,#6366f1,#a855f7)">' + (pos + 1) + '</span>' +
          '<input class="field flex-1 min-w-0 px-2 py-1.5 text-sm" data-k="title" value="' + escapeHtml(cap.title) + '" aria-label="Título do capítulo ' + (pos + 1) + '">' +
          '<button class="w-7 h-7 rounded-lg glass text-xs hover:bg-white/10" data-a="up" title="Mover para cima" aria-label="Mover para cima"' + (pos === 0 ? ' disabled' : '') + '>↑</button>' +
          '<button class="w-7 h-7 rounded-lg glass text-xs hover:bg-white/10" data-a="down" title="Mover para baixo" aria-label="Mover para baixo"' + (pos === estado.capitulos.length - 1 ? ' disabled' : '') + '>↓</button>' +
          '<span class="toggle ' + (cap.included ? 'on' : '') + '" role="switch" tabindex="0" aria-checked="' + (cap.included ? 'true' : 'false') + '" data-a="toggle" title="Incluir ou excluir da exportação"></span>' +
        '</div>' +
        '<div class="flex items-center gap-3 mt-1 pl-9">' +
          '<button class="text-[11px] text-slate-400 hover:text-violet-300 underline" data-a="open">ver prévia</button>' +
          '<span class="text-[11px] text-slate-500">' + cap.words.toLocaleString('pt-BR') + ' palavras</span>' +
        '</div>';

      const campo = linha.querySelector('[data-k="title"]');
      campo.addEventListener('input', () => { cap.title = campo.value; });
      linha.querySelectorAll('[data-a]').forEach(botao => {
        const acao = botao.dataset.a;
        if (acao === 'open') {
          botao.addEventListener('click', () => abrirPrevia(cap.index));
          return;
        }
        const disparar = () => {
          if (acao === 'toggle') cap.included = !cap.included;
          if (acao === 'up' && pos > 0) {
            const lista = estado.capitulos;
            [lista[pos - 1], lista[pos]] = [lista[pos], lista[pos - 1]];
          }
          if (acao === 'down' && pos < estado.capitulos.length - 1) {
            const lista = estado.capitulos;
            [lista[pos + 1], lista[pos]] = [lista[pos], lista[pos + 1]];
          }
          renderizarCapitulos();
        };
        botao.addEventListener('click', disparar);
        if (acao === 'toggle') {
          botao.addEventListener('keydown', e => {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); disparar(); }
          });
        }
      });
      lista.appendChild(linha);
    });
    atualizarEstatisticas();
  }

  function atualizarEstatisticas() {
    const incluidas = estado.capitulos.filter(c => c.included);
    const palavras = incluidas.reduce((soma, c) => soma + (c.words || 0), 0);
    $('#job-stats').textContent = estado.capitulos.length + ' capítulos · ' +
      incluidas.length + ' incluídos · ' + palavras.toLocaleString('pt-BR') +
      ' palavras · idioma ' + (estado.idioma || 'pt-BR');
    $('#btn-export').disabled = incluidas.length === 0;
  }

  async function abrirPrevia(indice) {
    const painel = $('#chapter-reader');
    try {
      const detalhe = await (await api('/api/jobs/' + estado.jobId + '/chapters/' + indice)).json();
      $('#reader-title').textContent = detalhe.title;
      $('#reader-body').textContent = (detalhe.paragraphs || []).join('\n\n');
      painel.classList.remove('hidden');
      painel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } catch (erro) {
      toast(erro.message, 'err');
    }
  }

  /* ---------- cancelar / exportar / recomeçar ---------- */
  $('#btn-cancel').addEventListener('click', async () => {
    if (!estado.jobId) return;
    try {
      await api('/api/jobs/' + estado.jobId + '/cancel', { method: 'POST' });
      $('#status-msg').textContent = 'Cancelando…';
    } catch (erro) {
      toast(erro.message, 'err');
    }
  });

  $('#btn-export').addEventListener('click', async () => {
    const incluidas = estado.capitulos.filter(c => c.included);
    if (!incluidas.length) { toast('Inclua ao menos um capítulo.', 'err'); return; }
    ocupado('#btn-export', true);
    try {
      const resposta = await api('/api/jobs/' + estado.jobId + '/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          chapters: estado.capitulos.map(c => ({ index: c.index, title: c.title, included: c.included }))
        })
      });
      baixar(await resposta.blob(), slug(estado.titulo) + '.epub');
      toast('EPUB validado e baixado.', 'ok');
    } catch (erro) {
      toast(erro.message, 'err');
    } finally {
      ocupado('#btn-export', false);
    }
  });

  $('#btn-restart').addEventListener('click', () => {
    pararTimer();
    estado.arquivo = null;
    estado.jobId = null;
    estado.capitulos = [];
    $('#file-name').textContent = '';
    $('#file-input').value = '';
    $('#chapter-reader').classList.add('hidden');
    $('#warn-box').classList.add('hidden');
    irParaPasso(1);
  });

  /* ---------- init ---------- */
  irParaPasso(1);
  checkApi();
})();
