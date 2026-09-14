(() => {
  try {
    const saved = localStorage.getItem('spicy-theme');
    document.documentElement.dataset.theme = saved === 'light' ? 'light' : 'dark';
  } catch (_) {
    document.documentElement.dataset.theme = 'dark';
  }
})();

