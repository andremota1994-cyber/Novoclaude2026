// Menu principal compartilhado por todas as páginas do admin.
// Uso: <div class="topbar" id="menu-principal"></div><script src="/static/menu.js"></script>
(function(){
  const ITENS = [
    {label: 'Início',      href: '/',            aba: 'chat'},
    {label: 'Visão Geral', href: '/?aba=overview',  aba: 'overview'},
    {label: 'Meta Ads',    href: '/?aba=dashboard', aba: 'dashboard'},
    {label: 'Faturamento', href: '/faturamento'},
    {label: 'Tarefas',     href: '/tarefas'},
    {label: 'Financeiro',  href: '/financeiro'},
    {label: 'Agenda',      href: '/agenda'},
    {label: 'Clientes',    href: '/clientes'},
    {label: 'Em negociação', href: '/negociacao'},
    {label: 'Gestores',    href: '/gestores'},
    {label: 'Dashboards',  href: '/dashboards'},
    {label: 'Expansão',    href: '/expansao'}
  ];

  // Menu em coluna fixa à esquerda; no celular vira uma barra no topo com botão de abrir.
  // Os links continuam com a classe topbar-link (a Início usa para marcar a aba ativa).
  const css = `
body.com-menu-lateral { padding-left: 224px; }
.menu-lateral { position: fixed; top: 0; left: 0; bottom: 0; width: 224px; z-index: 50; display: flex; flex-direction: column; gap: 18px; padding: 18px 12px 14px; border-right: 0.5px solid var(--border); background: linear-gradient(var(--card), var(--card)), var(--bg); overflow-y: auto; }
.menu-lateral .ml-topo { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 2px 8px; }
.menu-lateral .ml-logo { font-size: 15px; font-weight: 600; display: flex; align-items: center; gap: 9px; text-decoration: none; color: var(--text-primary); font-family: 'Sora', sans-serif; white-space: nowrap; }
.menu-lateral .ml-logo img { height: 24px; width: auto; display: block; }
.menu-lateral .ml-logo span { background: var(--grad); -webkit-background-clip: text; background-clip: text; color: transparent; }
.menu-lateral .ml-abrir { display: none; width: 36px; height: 36px; border-radius: 8px; border: 0.5px solid var(--border); background: transparent; color: var(--text-primary); cursor: pointer; align-items: center; justify-content: center; }
.menu-lateral .ml-abrir svg { width: 18px; height: 18px; }
.menu-lateral .ml-nav { display: flex; flex-direction: column; gap: 2px; }
.menu-lateral .ml-nav .topbar-link { display: flex; align-items: center; width: 100%; padding: 9px 12px; border-radius: 8px; font-size: 13.5px; color: var(--text-secondary); background: transparent; text-decoration: none; transition: background .15s, color .15s; }
.menu-lateral .ml-nav .topbar-link:hover { color: var(--text-primary); background: var(--card); }
.menu-lateral .ml-nav .topbar-link.active { color: var(--blue-bright, #f3d888); background: var(--card2, rgba(228,190,110,.10)); font-weight: 600; }
.menu-lateral .ml-nav .topbar-link:focus-visible, .menu-lateral .ml-abrir:focus-visible, .menu-lateral .olho-valores:focus-visible { outline: 2px solid var(--blue-bright, #f3d888); outline-offset: 1px; }
.menu-lateral .ml-rodape { margin-top: auto; display: flex; align-items: center; gap: 10px; padding: 12px 8px 0; border-top: 0.5px solid var(--border); font-size: 12px; color: var(--text-secondary); }
@media (max-width: 900px) {
  body.com-menu-lateral { padding-left: 0; }
  .menu-lateral { position: relative; bottom: auto; width: auto; z-index: 5; gap: 0; padding: 10px 16px; border-right: none; border-bottom: 0.5px solid var(--border); overflow: visible; flex-shrink: 0; }
  .menu-lateral .ml-topo { padding: 0; }
  .menu-lateral .ml-abrir { display: inline-flex; }
  .menu-lateral .ml-nav, .menu-lateral .ml-rodape { display: none; }
  .menu-lateral.aberto .ml-nav { display: flex; padding-top: 10px; }
  .menu-lateral.aberto .ml-rodape { display: flex; margin-top: 8px; padding-bottom: 4px; }
}
.olho-valores { width: 34px; height: 34px; border-radius: 8px; border: 0.5px solid var(--border); background: transparent; color: var(--text-secondary); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; transition: all .15s; }
.olho-valores:hover { color: var(--text-primary); background: var(--card); }
.olho-valores svg { width: 17px; height: 17px; }
body.ocultar-valores .olho-valores { color: var(--blue-bright, #f3d888); border-color: var(--border-strong, rgba(228,190,110,.3)); }
/* Valores em R$ borrados quando o olho está fechado */
.tem-valor, input.valor-input, input.field-input { transition: filter .15s; }
body.ocultar-valores .tem-valor, body.ocultar-valores input.valor-input, body.ocultar-valores input.field-input { filter: blur(7px); user-select: none; }`;
  const style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);

  const path = location.pathname.replace(/\/+$/, '') || '/';
  const naHome = path === '/';
  const abaAtual = new URLSearchParams(location.search).get('aba') || 'chat';

  function ativo(item){
    if (item.aba) return naHome && item.aba === abaAtual;
    if (item.href === '/clientes') return path === '/clientes' || path.startsWith('/cliente/');
    return path === item.href;
  }

  const links = ITENS.map(item =>
    `<a class="topbar-link${ativo(item) ? ' active' : ''}" href="${item.href}"${item.aba ? ` data-aba="${item.aba}"` : ''}>${item.label}</a>`
  ).join('');

  const el = document.getElementById('menu-principal');
  if (!el) return;
  el.classList.remove('topbar');
  el.classList.add('menu-lateral');
  document.body.classList.add('com-menu-lateral');
  el.innerHTML = `<div class="ml-topo"><a class="ml-logo" href="/"><img src="/static/logo.png" alt="Mobilli"> Mobilli <span>Digital</span></a>
  <button class="ml-abrir" id="ml-abrir" type="button" aria-expanded="false" aria-controls="topbar-nav" aria-label="Abrir menu"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"/></svg></button></div>
  <nav class="topbar-nav ml-nav" id="topbar-nav">${links}</nav>
  <div class="ml-rodape"><button class="olho-valores" id="olho-valores" type="button"></button><span id="olho-rotulo"></span></div>`;
  iniciarOcultarValores();

  // Celular: o botão abre e fecha a lista; escolher uma aba fecha
  const abrir = document.getElementById('ml-abrir');
  abrir.addEventListener('click', () => {
    const aberto = el.classList.toggle('aberto');
    abrir.setAttribute('aria-expanded', String(aberto));
    abrir.setAttribute('aria-label', aberto ? 'Fechar menu' : 'Abrir menu');
  });
  el.addEventListener('click', e => {
    if (e.target.closest('.topbar-link')) { el.classList.remove('aberto'); abrir.setAttribute('aria-expanded', 'false'); }
  });

  // Na Início, as abas trocam sem recarregar a página
  if (naHome) {
    el.querySelectorAll('[data-aba]').forEach(a => a.addEventListener('click', e => {
      if (typeof window.setPage !== 'function') return;
      e.preventDefault();
      window.setPage(a.dataset.aba, a);
      window.history.replaceState(null, '',a.dataset.aba === 'chat' ? '/' : a.getAttribute('href'));
    }));
  }

  // ── Olho: ocultar / mostrar valores em R$ ──
  function iniciarOcultarValores(){
    const OLHO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>';
    const OLHO_FECHADO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.6 5.1A10.4 10.4 0 0 1 12 5c6.5 0 10 7 10 7a17.6 17.6 0 0 1-2.3 3.2M6.6 6.6A17.4 17.4 0 0 0 2 12s3.5 7 10 7a9.6 9.6 0 0 0 5.4-1.6"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/><path d="M2 2l20 20"/></svg>';
    const btn = document.getElementById('olho-valores');
    let oculto = false;
    try { oculto = localStorage.getItem('ocultar-valores') === '1'; } catch (_) {}
    function aplicar(){
      document.body.classList.toggle('ocultar-valores', oculto);
      btn.innerHTML = oculto ? OLHO_FECHADO : OLHO;
      btn.title = oculto ? 'Mostrar valores' : 'Ocultar valores';
      btn.setAttribute('aria-label', btn.title);
      btn.setAttribute('aria-pressed', String(oculto));
      const rotulo = document.getElementById('olho-rotulo');
      if (rotulo) rotulo.textContent = btn.title;
    }
    btn.addEventListener('click', () => {
      oculto = !oculto;
      try { localStorage.setItem('ocultar-valores', oculto ? '1' : '0'); } catch (_) {}
      aplicar();
    });
    // Marca os elementos que mostram R$ (inclusive os que aparecem depois, ao carregar dados)
    const temReais = /R\$\s?-?\d/;
    function marcar(raiz){
      const andar = document.createTreeWalker(raiz, NodeFilter.SHOW_TEXT);
      let n;
      while ((n = andar.nextNode())) {
        const p = n.parentElement;
        if (p && !p.closest('script,style,.olho-valores') && temReais.test(n.nodeValue)) p.classList.add('tem-valor');
      }
    }
    let agendado = null;
    new MutationObserver(() => {
      if (agendado) return;
      agendado = requestAnimationFrame(() => { agendado = null; marcar(document.body); });
    }).observe(document.body, {childList: true, subtree: true, characterData: true});
    marcar(document.body);
    aplicar();
  }
})();
