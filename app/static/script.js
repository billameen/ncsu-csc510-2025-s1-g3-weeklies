// script.js – light enhancements for the simple Flask site
document.addEventListener('DOMContentLoaded', () => {
  // Mark active nav link
  const here = window.location.pathname.replace(/\/+$/,'') || '/';
  document.querySelectorAll('nav a[href]').forEach(a => {
    const path = a.getAttribute('href').replace(/\/+$/,'') || '/';
    if (path === here) a.setAttribute('aria-current', 'page');
  });

  // Confirm actions
  document.querySelectorAll('[data-confirm]').forEach(el => {
    el.addEventListener('click', (e) => {
      const msg = el.getAttribute('data-confirm') || 'Are you sure?';
      if (!confirm(msg)) e.preventDefault();
    });
  });

  // Simple auto-hide for flash messages
  document.querySelectorAll('.flash[data-autohide]').forEach(el => {
    const ms = parseInt(el.getAttribute('data-autohide'), 10) || 3500;
    setTimeout(() => { el.style.display = 'none'; }, ms);
  });
});
