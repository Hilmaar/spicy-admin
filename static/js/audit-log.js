(() => {
  const dialog = document.querySelector('#audit-detail-dialog');
  if (!dialog || typeof dialog.showModal !== 'function') return;
  const content = dialog.querySelector('[data-audit-content]');
  let opener, controller;
  dialog.querySelector('[data-audit-close]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { controller?.abort(); opener?.focus(); });
  document.querySelectorAll('[data-audit-row]').forEach(row => row.addEventListener('click', async event => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    opener = row.querySelector('[data-audit-detail]');
    controller?.abort();
    controller = new AbortController();
    content.textContent = 'Loading event…';
    if (!dialog.open) dialog.showModal();
    try {
      const response = await fetch(`${opener.href}?format=json`, {
        credentials: 'same-origin', signal: controller.signal, headers: {Accept: 'application/json'}
      });
      if (!response.ok) throw new Error('unavailable');
      const data = await response.json();
      const list = document.createElement('dl');
      for (const [label, value] of data.details) {
        const term = document.createElement('dt'); term.textContent = label;
        const definition = document.createElement('dd');
        const text = document.createElement('pre'); text.textContent = value;
        definition.append(text); list.append(term, definition);
      }
      content.replaceChildren(list);
    } catch (error) {
      if (error.name !== 'AbortError') content.textContent = 'Event details unavailable. Please try again.';
    }
  }));
})();
