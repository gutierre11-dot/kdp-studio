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

  /* ---------- lista de capítulos (agrupada por capítulo de nível 1) ---------- */
  function agrupar() {
    const grupos = [];
    estado.capitulos.forEach(cap => {
      if (cap.level === 1 || !grupos.length) {
        cap.aberto = cap.aberto !== false;
        grupos.push({ pai: cap, filhos: [] });
      } else {
        grupos[grupos.length - 1].filhos.push(cap);
      }
    });
    return grupos;
  }

  function aplicarInclusao(grupo, valor) {
    grupo.pai.included = valor;
    grupo.filhos.forEach(f => { f.included = valor; });
  }

  function moverGrupo(grupos, posicao, direcao) {
    const destino = posicao + direcao;
    if (destino < 0 || destino >= grupos.length) return;
    const a = grupos[Math.min(posicao, destino)];
    const b = grupos[Math.max(posicao, destino)];
    const blocoA = [a.pai].concat(a.filhos);
    const blocoB = [b.pai].concat(b.filhos);
    const inicio = estado.capitulos.indexOf(a.pai);
    const fim = estado.capitulos.indexOf(b.pai);
    if (inicio < 0 || fim < 0 || inicio > fim) return;
    estado.capitulos.splice(inicio, blocoA.length + blocoB.length,
                            ...blocoB, ...blocoA);
  }

  function botao(rotulo, titulo, aoClicar, desabilitado) {
    const b = document.createElement('button');
    b.className = 'w-7 h-7 rounded-lg glass text-xs hover:bg-white/10 disabled:opacity-30';
    b.textContent = rotulo;
    b.title = titulo;
    b.setAttribute('aria-label', titulo);
    if (desabilitado) b.disabled = true;
    b.addEventListener('click', aoClicar);
    return b;
  }

  function linhaCapitulo(cap, contexto) {
    const linha = document.createElement('div');
    linha.className = 'chapter-row flex items-center gap-2 rounded-xl px-2 py-1.5' +
      (cap.included ? '' : ' excluded');

    const campo = document.createElement('input');
    campo.className = 'field flex-1 min-w-0 px-2 py-1.5 text-sm';
    campo.value = cap.title;
    campo.setAttribute('aria-label', 'Título do capítulo');
    campo.addEventListener('input', () => { cap.title = campo.value; });
    linha.appendChild(campo);

    if (contexto.ehPai) {
      if (contexto.temFilhos) {
        linha.appendChild(botao(cap.aberto ? '▾' : '▸',
                                cap.aberto ? 'Recolher seções' : 'Expandir seções',
                                () => { cap.aberto = !cap.aberto; renderizarCapitulos(); }));
      }
      linha.appendChild(botao('↑', 'Mover capítulo para cima',
                              () => { moverGrupo(agrupar(), contexto.posicaoGrupo, -1);
                                      renderizarCapitulos(); },
                              contexto.posicaoGrupo === 0));
      linha.appendChild(botao('↓', 'Mover capítulo para baixo',
                              () => { moverGrupo(agrupar(), contexto.posicaoGrupo, 1);
                                      renderizarCapitulos(); },
                              contexto.ultimoGrupo));
    }

    const palavras = document.createElement('span');
    palavras.className = 'text-[11px] text-slate-500 shrink-0 hidden sm:inline';
    palavras.textContent = cap.words.toLocaleString('pt-BR') + ' pal.';
    linha.appendChild(palavras);

    const alternar = document.createElement('span');
    alternar.className = 'toggle ' + (cap.included ? 'on' : '');
    alternar.setAttribute('role', 'switch');
    alternar.setAttribute('aria-checked', cap.included ? 'true' : 'false');
    alternar.setAttribute('tabindex', '0');
    alternar.title = 'Incluir ou excluir da exportação';
    const disparar = () => {
      if (contexto.ehPai && contexto.grupo) {
        aplicarInclusao(contexto.grupo, !contexto.grupo.pai.included);
      } else {
        cap.included = !cap.included;
      }
      renderizarCapitulos();
    };
    alternar.addEventListener('click', disparar);
    alternar.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); disparar(); }
    });
    linha.appendChild(alternar);

    const ver = document.createElement('button');
    ver.className = 'text-[11px] text-slate-400 hover:text-violet-300 underline shrink-0';
    ver.textContent = 'prévia';
    ver.addEventListener('click', () => abrirPrevia(cap.index));
    linha.appendChild(ver);

    if (!contexto.ehPai) linha.classList.add('bg-white/[.02]');
    return linha;
  }

  function renderizarCapitulos() {
    const lista = $('#chapters-list');
    lista.innerHTML = '';
    const grupos = agrupar();
    grupos.forEach((grupo, gi) => {
      const cartao = document.createElement('div');
      cartao.className = 'glass rounded-2xl p-2';
      cartao.appendChild(linhaCapitulo(grupo.pai, {
        ehPai: true,
        grupo: grupo,
        temFilhos: grupo.filhos.length > 0,
        posicaoGrupo: gi,
        ultimoGrupo: gi === grupos.length - 1,
      }));
      if (grupo.filhos.length && grupo.pai.aberto) {
        const sub = document.createElement('div');
        sub.className = 'mt-1 pl-3 border-l border-white/10 space-y-1';
        grupo.filhos.forEach(filho => sub.appendChild(
          linhaCapitulo(filho, { ehPai: false })));
        cartao.appendChild(sub);
      } else if (grupo.filhos.length) {
        const resumo = document.createElement('p');
        resumo.className = 'text-[11px] text-slate-500 pl-3 mt-1';
        resumo.textContent = grupo.filhos.length + ' seções recolhidas';
        cartao.appendChild(resumo);
      }
      lista.appendChild(cartao);
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
