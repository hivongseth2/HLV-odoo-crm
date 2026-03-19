/**
 * toast.js — Toast Notification System
 * Provides global `toast` object with success/error/info/warn/show methods.
 */
const toast = (() => {
  let host = document.getElementById('toastHost');
  if (!host) {
    host = document.createElement('div');
    host.id = 'toastHost';
    host.className = 'toast-host';
    document.body.appendChild(host);
  }
  const push = (type, message, { title = '', ms = 2500 } = {}) => {
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.innerHTML = `
    ${title ? `<div class="title">${title}</div>` : ''}
    <div class="msg">${message}</div>
    <div class="close" title="Đóng">×</div>
  `;
    host.appendChild(el);
    requestAnimationFrame(() => el.classList.add('show'));
    const close = () => { el.classList.remove('show'); setTimeout(() => el.remove(), 200); };
    el.querySelector('.close').addEventListener('click', close);
    if (ms > 0) setTimeout(close, ms);
  };
  return {
    success: (m, o) => push('success', m, o),
    error: (m, o) => push('error', m, o),
    info: (m, o) => push('info', m, o),
    warn: (m, o) => push('warn', m, o),
    show: push,
  };
})();
