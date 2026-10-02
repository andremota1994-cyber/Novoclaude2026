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
  <nav class="topbar-nav" id="topbar-nav">${links}</nav>`;

  // Na Início, as abas trocam sem recarregar a página
  if (naHome) {
    el.querySelectorAll('[data-aba]').forEach(a => a.addEventListener('click', e => {
      if (typeof window.setPage !== 'function') return;
      e.preventDefault();
      window.setPage(a.dataset.aba, a);
      window.history.replaceState(null, '',a.dataset.aba === 'chat' ? '/' : a.getAttribute('href'));
    }));
  }
})();
