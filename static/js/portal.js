(() => {
  const themeButton = document.querySelector('[data-theme-toggle]');
  const updateLabel = () => {
    if (themeButton) themeButton.setAttribute('aria-label',
      `Switch to ${document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'} theme`);
  };
  updateLabel();
  themeButton?.addEventListener('click', () => {
    const theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('spicy-theme', theme); } catch (_) { /* Optional persistence. */ }
    updateLabel();
  });
  const menu = document.querySelector('[data-menu-toggle]');
  const backdrop = document.querySelector('[data-menu-close]');
  const sidebar = document.querySelector('#sidebar');
  const setMenu = (open) => {
    document.body.classList.toggle('menu-open', open);
    menu?.setAttribute('aria-expanded', String(open));
    if (backdrop) backdrop.hidden = !open;
    if (open) sidebar?.querySelector('a')?.focus();
    else menu?.focus();
  };
  menu?.addEventListener('click', () => setMenu(menu.getAttribute('aria-expanded') !== 'true'));
  backdrop?.addEventListener('click', () => setMenu(false));
  document.addEventListener('keydown', (event) => {
    if (!document.body.classList.contains('menu-open')) return;
    if (event.key === 'Escape') setMenu(false);
    if (event.key === 'Tab') {
      const links = sidebar.querySelectorAll('a');
      const first = links[0], last = links[links.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus();
      }
    }
  });
  matchMedia('(min-width: 901px)').addEventListener('change', (event) => {
    if (event.matches && document.body.classList.contains('menu-open')) setMenu(false);
  });
})();

