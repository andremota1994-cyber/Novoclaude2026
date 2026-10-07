// Notificações do painel no celular: registra o service worker e mostra o botão
// "Ativar notificações" até a pessoa ativar neste aparelho.
(function(){
  if (!('serviceWorker' in navigator)) return;
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const instalado = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  const suporta = 'PushManager' in window && 'Notification' in window;

  const css = `
.push-btn { position: fixed; right: 16px; bottom: 16px; z-index: 200; display: flex; align-items: center; gap: 8px;
  padding: 11px 16px; border-radius: 24px; border: none; cursor: pointer; font-family: inherit; font-size: 13px; font-weight: 600;
  background: linear-gradient(135deg, #f3d888, #9c7a24); color: #171206; box-shadow: 0 8px 24px rgba(0,0,0,.45); }
.push-btn .x { margin-left: 4px; opacity: .6; font-weight: 400; padding: 0 2px; }
.push-dica { position: fixed; left: 16px; right: 16px; bottom: 16px; z-index: 200; background: #17130c; color: #f7f3ea;
  border: 1px solid rgba(228,190,110,.3); border-radius: 14px; padding: 12px 14px; font-size: 12.5px; line-height: 1.5;
  box-shadow: 0 8px 24px rgba(0,0,0,.45); font-family: inherit; }
.push-dica b { color: #f3d888; }
.push-dica button { float: right; background: none; border: none; color: #a89a78; font-size: 16px; cursor: pointer; margin-left: 8px; }`;

  function fechadoAgora(chave){ try { return localStorage.getItem(chave) === new Date().toDateString(); } catch (_) { return false; } }
  function fecharHoje(chave){ try { localStorage.setItem(chave, new Date().toDateString()); } catch (_) {} }

  function addCss(){ const s = document.createElement('style'); s.textContent = css; document.head.appendChild(s); }

  function chaveBytes(b64){
    const pad = '='.repeat((4 - b64.length % 4) % 4);
    const raw = atob((b64 + pad).replace(/-/g, '+').replace(/_/g, '/'));
    return Uint8Array.from([...raw].map(c => c.charCodeAt(0)));
  }

  async function ativar(btn){
    btn.disabled = true; btn.firstChild.textContent = 'Ativando…';
    try {
      const perm = await Notification.requestPermission();
      if (perm !== 'granted') { alert('As notificações foram bloqueadas. Para ativar depois, libere nas configurações do celular.'); btn.remove(); return; }
      const reg = await navigator.serviceWorker.ready;
      const j = await (await fetch('/api/push/chave')).json();
      if (!j.ok) throw new Error(j.error || 'chave indisponível');
      const inscricao = await reg.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: chaveBytes(j.chave)});
      const r = await fetch('/api/push/inscrever', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({inscricao: inscricao.toJSON(), aparelho: navigator.userAgent})});
      const jr = await r.json();
      if (!jr.ok) throw new Error(jr.error);
      btn.remove();
      fetch('/api/push/teste', {method: 'POST'});
    } catch (e) {
      alert('Não foi possível ativar as notificações: ' + e.message);
      btn.disabled = false; btn.firstChild.textContent = '🔔 Ativar notificações';
    }
  }

  async function iniciar(){
    let reg;
    try { reg = await navigator.serviceWorker.register('/sw.js', {scope: '/'}); } catch (_) { return; }
    // iPhone: notificação só funciona no app salvo na tela de início
    if (ios && !instalado) {
      if (fechadoAgora('push-dica-ios')) return;
      addCss();
      const d = document.createElement('div');
      d.className = 'push-dica';
      d.innerHTML = '<button aria-label="Fechar">✕</button>🔔 Para receber notificações no iPhone, abra o painel pelo <b>ícone da Mobilli na tela de início</b>. Se você salvou antes, apague o ícone e salve de novo (Compartilhar → Adicionar à Tela de Início).';
      d.querySelector('button').onclick = () => { fecharHoje('push-dica-ios'); d.remove(); };
      document.body.appendChild(d);
      return;
    }
    if (!suporta || Notification.permission === 'denied') return;
    await navigator.serviceWorker.ready;
    const atual = await reg.pushManager.getSubscription();
    if (atual && Notification.permission === 'granted') {
      // Mantém a inscrição deste aparelho em dia no servidor
      fetch('/api/push/inscrever', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({inscricao: atual.toJSON(), aparelho: navigator.userAgent})}).catch(() => {});
      return;
    }
    if (fechadoAgora('push-btn')) return;
    addCss();
    const btn = document.createElement('button');
    btn.className = 'push-btn';
    btn.innerHTML = '<span>🔔 Ativar notificações</span><span class="x" title="Agora não">✕</span>';
    btn.onclick = e => {
      if (e.target.classList.contains('x')) { fecharHoje('push-btn'); btn.remove(); return; }
      ativar(btn);
    };
    document.body.appendChild(btn);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', iniciar); else iniciar();
})();
