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
  function contarPalavras(texto) {
    return String(texto || '').trim().split(/\s+/).filter(Boolean).length;
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
  const estado = {
    arquivo: null, jobId: null, capitulos: [], timer: null, online: false,
    capa: null,   // metadados da capa efetiva ({kind, name, bytes})
    editado: false,   // há edições locais ainda não exportadas
  };

  // Sem o nome amigável aqui, o selo de status mostraria o id cru do provider.
  const PROVEDORES = { deepseek: 'DeepSeek', openai: 'OpenAI', gemini: 'Gemini', offline: 'sem IA' };

  // Bandeiras por idioma. O catálogo real (código -> nome) vem de /api/config.
  const BANDEIRAS = {
    'pt-BR': '🇧🇷', 'pt-PT': '🇵🇹', pt: '🇵🇹', en: '🇺🇸', es: '🇪🇸', fr: '🇫🇷',
    de: '🇩🇪', it: '🇮🇹', nl: '🇳🇱', ja: '🇯🇵', zh: '🇨🇳', ru: '🇷🇺',
  };

  function idiomaCanonico(codigo) {
    const bruto = String(codigo || '').toLowerCase();
    if (bruto === 'pt-br') return 'pt-BR';
    if (bruto === 'pt-pt') return 'pt-PT';
    return bruto;
  }

  function rotuloIdioma(codigo, nome) {
    const canon = idiomaCanonico(codigo);
    const bandeira = BANDEIRAS[canon] || BANDEIRAS[codigo] || '🌐';
    const texto = String(nome || canon);
    return bandeira + ' ' + texto.charAt(0).toUpperCase() + texto.slice(1);
  }

  /** Monta os dois selects de idioma a partir do catálogo servido pela API. */
  function popularIdiomas(catalogo) {
    const vistos = new Set();
    const opcoes = Object.keys(catalogo || {}).map(codigo => ({
      codigo: idiomaCanonico(codigo),
      rotulo: rotuloIdioma(codigo, catalogo[codigo]),
    })).filter(opcao => {
      // `pt-br` e `pt-BR` canonicalizam para o mesmo código: fica um só.
      if (vistos.has(opcao.codigo)) return false;
      vistos.add(opcao.codigo);
      return true;
    }).sort((a, b) => a.rotulo.localeCompare(b.rotulo, 'pt-BR'));

    const html = opcoes.map(opcao => '<option value="' + escapeHtml(opcao.codigo) +
      '">' + escapeHtml(opcao.rotulo) + '</option>').join('');

    const destino = $('#tr-to');
    const alvoAtual = destino.value || 'pt-BR';
    destino.innerHTML = html;
    destino.value = opcoes.some(o => o.codigo === alvoAtual) ? alvoAtual : 'pt-BR';

    const origem = $('#tr-from');
    const origemAtual = origem.value || 'auto';
    origem.innerHTML = '<option value="auto">🌐 Detectar automaticamente</option>' + html;
    origem.value = (origemAtual === 'auto' || opcoes.some(o => o.codigo === origemAtual))
      ? origemAtual : 'auto';
  }

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
      const selo = $('#api-status');
      selo.innerHTML = '<span class="text-emerald-400">●</span> Conectado · ' +
        escapeHtml(PROVEDORES[cfg.provider] || cfg.provider);
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

      popularIdiomas(cfg.languages);

      if (!cfg.configured) {
        desabilitarToggle('#tg-translate', 'Nenhuma chave de IA configurada no servidor.');
        $('#tr-opts').classList.add('hidden');
        $('#tr-privacy').classList.add('hidden');
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
  ligarToggle('#tg-translate', atualizarAvisoTraducao);

  /** Mostra as opções de tradução e o aviso de que o texto sai da máquina. */
  function atualizarAvisoTraducao() {
    const ativo = ligado('#tg-translate');
    $('#tr-opts').classList.toggle('hidden', !ativo);
    $('#tr-privacy').classList.toggle('hidden', !ativo);
  }

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
    dados.append('description', $('#inp-description').value.trim());
    dados.append('publisher', $('#inp-publisher').value.trim());
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
      notes_count: c.notes_count || 0,
      // Texto corrigido no navegador e ainda não exportado (null = original).
      edit: null,
    }));
    // Edições salvas no navegador para este job têm prioridade sobre o original.
    const restaurados = restaurarEdicoes(estado.jobId, estado.capitulos);
    estado.capa = job.cover || null;
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
    atualizarCapa();
    irParaPasso(3);
    toast('Conversão concluída: ' + estado.capitulos.length + ' capítulos.', 'ok');
    if (restaurados) {
      toast('Edições restauradas do salvamento local: ' + restaurados +
        (restaurados === 1 ? ' capítulo.' : ' capítulos.'), 'info');
    }
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

    // As notas viram endnotes no fim do capítulo: avisar aqui evita descobrir
    // a associação só depois de exportar o EPUB.
    if (cap.notes_count) {
      const notas = document.createElement('span');
      notas.className = 'text-[11px] text-amber-300/80 shrink-0 hidden sm:inline';
      notas.textContent = cap.notes_count + (cap.notes_count > 1 ? ' notas' : ' nota');
      notas.title = 'Notas de rodapé deste capítulo (viram endnotes no EPUB)';
      linha.appendChild(notas);
    }

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
    ver.addEventListener('click', () => abrirCapitulo(cap.index, false));
    linha.appendChild(ver);

    const editar = document.createElement('button');
    editar.className = 'text-[11px] underline shrink-0 ' + (cap.edit
      ? 'text-emerald-300 font-bold'
      : 'text-slate-400 hover:text-violet-300');
    editar.textContent = cap.edit ? 'editado' : 'editar';
    editar.title = 'Corrigir o texto deste capítulo antes de exportar';
    editar.addEventListener('click', () => abrirCapitulo(cap.index, true));
    linha.appendChild(editar);

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

  /* ---------- painel de leitura e edição ---------- */
  let leituraAtual = null;   // {index, title, paragraphs, notes, title_refs}

  async function abrirCapitulo(indice, modoEdicao) {
    const painel = $('#chapter-reader');
    const cap = estado.capitulos.find(c => c.index === indice);
    if (!cap) return;
    try {
      const detalhe = await (await api('/api/jobs/' + estado.jobId +
        '/chapters/' + indice)).json();
      leituraAtual = {
        index: indice,
        title: detalhe.title,
        paragraphs: (detalhe.paragraphs || []).slice(),
        notes: detalhe.notes || [],
        title_refs: detalhe.title_refs || [],
      };
      // Uma correção local ainda não exportada tem prioridade sobre o original.
      if (Array.isArray(cap.edit) && cap.edit.length) leituraAtual.paragraphs = cap.edit.slice();
    } catch (erro) {
      toast(erro.message, 'err');
      return;
    }
    $('#reader-title').textContent = cap.title || leituraAtual.title;
    definirModoLeitura(!modoEdicao);
    painel.classList.remove('hidden');
    painel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function definirModoLeitura(somenteLeitura) {
    if (!leituraAtual) return;
    const body = $('#reader-body');
    body.innerHTML = '';
    if (somenteLeitura) {
      body.className = 'text-stone-700 leading-relaxed text-[15px] whitespace-pre-line max-h-[320px] overflow-y-auto';
      leituraAtual.paragraphs.forEach(texto => {
        const p = document.createElement('p');
        p.className = 'mb-3';
        p.textContent = texto;
        body.appendChild(p);
      });
    } else {
      body.className = 'max-h-[320px] overflow-y-auto space-y-2';
      // Um textarea por parágrafo: o usuário não precisa adivinhar separador.
      leituraAtual.paragraphs.forEach((texto, i) => {
        const area = document.createElement('textarea');
        area.className = 'field w-full px-2 py-1.5 text-[14px] leading-relaxed';
        area.rows = Math.min(12, Math.max(2, Math.ceil(texto.length / 70)));
        area.value = texto;
        area.setAttribute('aria-label', 'Parágrafo ' + (i + 1));
        body.appendChild(area);
      });
    }
    $('#reader-mode').textContent = somenteLeitura ? 'Prévia do capítulo' : 'Editando o capítulo';
    $('#btn-reader-edit').classList.toggle('hidden', !somenteLeitura);
    $('#btn-reader-save').classList.toggle('hidden', somenteLeitura);
    $('#btn-reader-cancel').classList.toggle('hidden', somenteLeitura);
    // A dica dos tokens ⟦N⟧ só faz sentido enquanto o texto é editável.
    $('#reader-hint').classList.toggle('hidden', somenteLeitura || !leituraAtual.notes.length);
    renderizarNotas(leituraAtual.notes);
    atualizarMarcaEdicao();
  }

  function renderizarNotas(notas) {
    const caixa = $('#reader-notes');
    caixa.innerHTML = '';
    if (!notas || !notas.length) { caixa.classList.add('hidden'); return; }
    caixa.classList.remove('hidden');
    const titulo = document.createElement('p');
    titulo.className = 'font-bold mb-1';
    titulo.textContent = 'Notas de rodapé (viram endnotes no fim deste capítulo)';
    caixa.appendChild(titulo);
    const lista = document.createElement('ol');
    lista.className = 'list-decimal list-inside space-y-1';
    notas.forEach(par => {
      const li = document.createElement('li');
      li.value = par[0];          // mantém o número do chamador no texto
      li.textContent = par[1];
      lista.appendChild(li);
    });
    caixa.appendChild(lista);
  }

  function atualizarMarcaEdicao() {
    const cap = estado.capitulos.find(c => leituraAtual && c.index === leituraAtual.index);
    $('#reader-edited').classList.toggle('hidden', !(cap && cap.edit));
  }

  $('#btn-reader-edit').addEventListener('click', () => definirModoLeitura(false));
  $('#btn-reader-cancel').addEventListener('click', () => {
    if (!leituraAtual) return;
    const cap = estado.capitulos.find(c => c.index === leituraAtual.index);
    if (cap && cap.edit) leituraAtual.paragraphs = cap.edit.slice();
    definirModoLeitura(true);
  });

  $('#btn-reader-save').addEventListener('click', () => {
    if (!leituraAtual) return;
    const cap = estado.capitulos.find(c => c.index === leituraAtual.index);
    if (!cap) return;
    const textos = Array.prototype.map.call(
      $('#reader-body').querySelectorAll('textarea'), area => area.value);
    // Parágrafo esvaziado sai do capítulo: é assim que se remove um trecho.
    const limpos = textos.map(t => t.trim()).filter(t => t.length > 0);
    if (!limpos.length) {
      toast('O capítulo ficaria vazio — use o interruptor para excluí-lo.', 'err');
      return;
    }
    cap.edit = limpos;
    cap.words = contarPalavras(limpos.join(' '));
    estado.editado = true;
    persistirEdicoes();
    leituraAtual.paragraphs = limpos.slice();
    definirModoLeitura(true);
    renderizarCapitulos();
    toast('Texto do capítulo atualizado.', 'ok');
  });

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

  /** Edições locais no formato que a API espera: {índice: [parágrafos]}. */
  function coletarEdicoes() {
    const edicoes = {};
    estado.capitulos.forEach(c => {
      if (Array.isArray(c.edit) && c.edit.length) edicoes[c.index] = c.edit;
    });
    return edicoes;
  }

  /* ---------- edições salvas no navegador ---------- */
  const PREFIXO_EDICOES = 'kdp-studio:edits:';

  function chaveEdicoes(jobId) {
    return PREFIXO_EDICOES + jobId;
  }

  /** Lê as edições salvas do job; localStorage indisponível ou JSON inválido vira null. */
  function lerEdicoes(jobId) {
    if (!jobId) return null;
    try {
      const bruto = window.localStorage.getItem(chaveEdicoes(jobId));
      if (!bruto) return null;
      const dados = JSON.parse(bruto);
      if (!dados || typeof dados !== 'object' || Array.isArray(dados)) return null;
      return dados;
    } catch (_) {
      return null;
    }
  }

  /** Falhas do localStorage são silenciosas: a edição continua em memória. */
  function gravarEdicoes(jobId, edicoes) {
    if (!jobId) return;
    try {
      window.localStorage.setItem(chaveEdicoes(jobId), JSON.stringify(edicoes));
    } catch (_) { /* modo privado, cota excedida etc. */ }
  }

  function limparEdicoes(jobId) {
    if (!jobId) return;
    try { window.localStorage.removeItem(chaveEdicoes(jobId)); } catch (_) { /* idem */ }
  }

  function persistirEdicoes() {
    if (!estado.jobId) return;
    gravarEdicoes(estado.jobId, coletarEdicoes());
  }

  /**
   * Reaplica ao job recém-convertido as edições salvas para o mesmo id.
   * Entradas inválidas ou de capítulos inexistentes são ignoradas em silêncio.
   */
  function restaurarEdicoes(jobId, capitulos) {
    const salvas = lerEdicoes(jobId);
    if (!salvas) return 0;
    let restaurados = 0;
    Object.keys(salvas).forEach(chave => {
      if (!/^\d+$/.test(chave)) return;
      const paragrafos = salvas[chave];
      if (!Array.isArray(paragrafos) || !paragrafos.length) return;
      if (!paragrafos.every(p => typeof p === 'string')) return;
      const cap = capitulos.find(c => c.index === Number(chave));
      if (!cap) return;
      const textos = paragrafos.map(p => p.trim()).filter(Boolean);
      if (!textos.length) return;
      cap.edit = textos;
      cap.words = contarPalavras(textos.join(' '));
      restaurados += 1;
    });
    if (restaurados) estado.editado = true;
    return restaurados;
  }

  $('#btn-export').addEventListener('click', async () => {
    const incluidas = estado.capitulos.filter(c => c.included);
    if (!incluidas.length) { toast('Inclua ao menos um capítulo.', 'err'); return; }
    ocupado('#btn-export', true);
    try {
      const resposta = await api('/api/jobs/' + estado.jobId + '/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          chapters: estado.capitulos.map(c => ({ index: c.index, title: c.title, included: c.included })),
          edit: coletarEdicoes(),
          cover: $('#ck-cover').checked,
        })
      });
      baixar(await resposta.blob(), slug(estado.titulo) + '.epub');
      // A chave fica salva: o usuário pode reexportar sem perder as edições.
      estado.editado = false;
      toast('EPUB validado e baixado.', 'ok');
    } catch (erro) {
      toast(erro.message, 'err');
    } finally {
      ocupado('#btn-export', false);
    }
  });

  $('#btn-restart').addEventListener('click', () => {
    pararTimer();
    limparEdicoes(estado.jobId);
    estado.editado = false;
    estado.arquivo = null;
    estado.jobId = null;
    estado.capitulos = [];
    estado.capa = null;
    leituraAtual = null;
    $('#file-name').textContent = '';
    $('#file-input').value = '';
    $('#chapter-reader').classList.add('hidden');
    $('#warn-box').classList.add('hidden');
    $('#reader-notes').classList.add('hidden');
    $('#reader-edited').classList.add('hidden');
    $('#reader-hint').classList.add('hidden');
    $('#inp-description').value = '';
    $('#inp-publisher').value = '';
    $('#cover-input').value = '';
    $('#ck-cover').checked = true;
    $('#cover-thumb').removeAttribute('src');
    irParaPasso(1);
  });

  /* ---------- capa ---------- */
  function atualizarCapa() {
    $('#cover-input').value = '';
    const enviada = !!estado.capa && estado.capa.kind === 'upload';
    $('#cover-status').textContent = enviada
      ? ('Sua capa: ' + (estado.capa.name || 'imagem enviada'))
      : 'Capa gerada automaticamente';
    $('#cover-hint').textContent = enviada
      ? 'A imagem enviada substitui a capa gerada no EPUB.'
      : 'Título e autor sobre um fundo sóbrio, em 1600×2560 (proporção KDP 1:1.6).';
    $('#btn-cover-reset').classList.toggle('hidden', !enviada);
    if (estado.jobId) {
      // A prévia vem do servidor: é a mesma imagem que entra no EPUB.
      $('#cover-thumb').src = '/api/jobs/' + estado.jobId + '/cover?t=' + Date.now();
    }
  }

  $('#btn-cover-upload').addEventListener('click', () => $('#cover-input').click());

  $('#cover-input').addEventListener('change', async () => {
    const arquivo = $('#cover-input').files[0];
    if (!arquivo || !estado.jobId) return;
    if (!/^image\/(jpeg|png)$/.test(arquivo.type)) {
      toast('A capa precisa ser uma imagem JPEG ou PNG.', 'err');
      atualizarCapa();
      return;
    }
    const dados = new FormData();
    dados.append('file', arquivo);
    ocupado('#btn-cover-upload', true);
    try {
      const resposta = await api('/api/jobs/' + estado.jobId + '/cover',
                                 { method: 'POST', body: dados });
      estado.capa = (await resposta.json()).cover;
      atualizarCapa();
      toast('Capa enviada.', 'ok');
    } catch (erro) {
      toast(erro.message, 'err');
      atualizarCapa();
    } finally {
      ocupado('#btn-cover-upload', false);
    }
  });

  $('#btn-cover-reset').addEventListener('click', async () => {
    if (!estado.jobId) return;
    try {
      const resposta = await api('/api/jobs/' + estado.jobId + '/cover',
                                 { method: 'DELETE' });
      estado.capa = (await resposta.json()).cover;
      atualizarCapa();
      toast('Voltou para a capa gerada automaticamente.', 'info');
    } catch (erro) {
      toast(erro.message, 'err');
    }
  });

  /* ---------- aviso ao sair com edições não exportadas ---------- */
  window.addEventListener('beforeunload', event => {
    if (!estado.editado) return;
    event.preventDefault();
    event.returnValue = '';
  });

  /* ---------- init ---------- */
  irParaPasso(1);
  checkApi();
})();
