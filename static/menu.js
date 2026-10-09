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
    {label: 'Gestores',    href: '/gestores'}
  ];

  const css = `
.topbar { display: flex; justify-content: space-between; align-items: center; padding: 0.75rem 1.5rem; border-bottom: 0.5px solid var(--border); flex-shrink: 0; flex-wrap: wrap; gap: 8px; position: relative; z-index: 2; }
.topbar-logo { font-size: 15px; font-weight: 600; display: flex; align-items: center; gap: 9px; text-decoration: none; color: var(--text-primary); font-family: 'Sora', sans-serif; }
.topbar-logo img { height: 24px; width: auto; display: block; }
.topbar-logo span { background: var(--grad); -webkit-background-clip: text; background-clip: text; color: transparent; }
.topbar-nav { display: flex; gap: 2px; flex-wrap: wrap; justify-content: flex-end; }
.topbar-link { padding: 6px 14px; border-radius: 8px; font-size: 13px; color: var(--text-secondary); cursor: pointer; border: none; background: transparent; font-family: inherit; transition: all 0.15s; text-decoration: none; display: inline-block; }
.topbar-link:hover { color: var(--text-primary); background: var(--card); }
.topbar-link.active { color: var(--text-primary); }
.topbar-dir { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
.olho-valores { width: 34px; height: 34px; border-radius: 8px; border: 0.5px solid var(--border); background: transparent; color: var(--text-secondary); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; transition: all .15s; }
.olho-valores:hover { color: var(--text-primary); background: var(--card); }
.olho-valores svg { width: 17px; height: 17px; }
body.ocultar-valores .olho-valores { color: var(--blue-bright, #f3d888); border-color: var(--border-strong, rgba(228,190,110,.3)); }
/* Valores em R$ borrados quando o olho está fechado */
.tem-valor, input.valor-input, input.field-input { transition: filter .15s; }
body.ocultar-valores .tem-valor, body.ocultar-valores input.valor-input, body.ocultar-valores input.field-input { filter: blur(7px); user-select: none; }
@media (max-width: 560px) {
  .topbar { padding: 0.6rem 1rem; }
  .topbar-link { padding: 6px 10px; font-size: 12px; }
}`;
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
  el.innerHTML = `<a class="topbar-logo" href="/"><img src="/static/logo.png" alt="Mobilli"> Mobilli <span>Digital</span></a>
  <div class="topbar-dir"><nav class="topbar-nav" id="topbar-nav">${links}</nav>
  <button class="olho-valores" id="olho-valores" type="button"></button></div>`;
  iniciarOcultarValores();

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
