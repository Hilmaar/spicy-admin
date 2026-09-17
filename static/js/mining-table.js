/* Local-only preferences; counts and precise ratios always come from the server. */
(() => {
  const audit = document.querySelector('#mining-audit-config');
  const preferences = {};
  const hidden = document.querySelector('[data-current-thresholds]');
  const remember = (table, value) => {
    preferences[table] = Number(value);
    if (hidden) hidden.value = JSON.stringify(preferences);
  };
  const reportChange = (table, oldValue, newValue) => {
    if (!audit || oldValue === newValue) return;
    fetch(audit.dataset.url, {
      method: 'POST', credentials: 'same-origin', keepalive: true,
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': audit.dataset.token},
      body: JSON.stringify({event_type: 'analytics.threshold_changed', table,
        old_threshold: Number(oldValue), new_threshold: Number(newValue)})
    }).catch(() => {}); // Audit availability must never gate a local preference.
  };
  const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
  document.querySelectorAll('[data-mining-table]').forEach(section => {
    const select = section.querySelector('[data-sample-threshold]');
    const body = section.querySelector('tbody');
    const key = `spicy:mining:threshold:v1:${section.dataset.tableKey}`;
    const allowed = [...select.options].map(option => option.value);
    let threshold = section.dataset.defaultThreshold;
    try {
      const stored = localStorage.getItem(key);
      if (allowed.includes(stored)) threshold = stored;
    } catch (_) { /* Storage can be unavailable; the controls still work. */ }
    select.value = threshold;
    remember(section.dataset.tableKey, threshold);
    section.querySelector('.sample-control').hidden = false;
    let refresh = () => {};
    select.addEventListener('change', () => {
      if (!allowed.includes(select.value)) return;
      const previous = threshold;
      threshold = select.value;
      remember(section.dataset.tableKey, threshold);
      try { localStorage.setItem(key, threshold); } catch (_) { /* Optional persistence. */ }
      refresh();
      reportChange(section.dataset.tableKey, previous, threshold);
    });
    if (!body) return;
    const rows = [...body.rows].map(element => ({
      element, name: element.dataset.player, uuid: element.dataset.uuid,
      target: BigInt(element.dataset.target), base: BigInt(element.dataset.base)
    }));
    let column = 'rate';
    let direction = 'descending';
    const buttons = [...section.querySelectorAll('[data-sort]')];
    buttons.forEach(button => { button.disabled = false; });
    const tie = (a, b) => compare(a.name.toLowerCase(), b.name.toLowerCase()) ||
      compare(a.name, b.name) || compare(a.uuid, b.uuid);
    function order(a, b) {
      const small = compare(a.base < BigInt(threshold), b.base < BigInt(threshold));
      if (small) return small;
      let result;
      if (column === 'player') result = compare(a.name.toLowerCase(), b.name.toLowerCase());
      else if (column === 'target' || column === 'base') result = compare(a[column], b[column]);
      else {
        const denominator = column === 'rate' ? 'base' : 'target';
        const numerator = column === 'rate' ? 'target' : 'base';
        const missing = compare(a[denominator] === 0n, b[denominator] === 0n);
        if (missing) return missing; // Missing values last in either direction/sample class.
        // Compare exact fractions, not rounded display values or floating-point counts.
        result = compare(a[numerator] * b[denominator], b[numerator] * a[denominator]);
      }
      return (direction === 'ascending' ? result : -result) || tie(a, b);
    }
    function render() {
      for (const row of rows.sort(order)) {
        const small = row.base < BigInt(threshold);
        row.element.querySelector('.sample-badge').hidden = !small;
        row.element.querySelectorAll('[data-ratio]').forEach(cell => {
          cell.classList.toggle('ratio-muted', small);
        });
        body.append(row.element);
      }
      buttons.forEach(button => {
        const active = button.dataset.sort === column;
        button.closest('th').setAttribute('aria-sort', active ? direction : 'none');
      });
      const label = buttons.find(button => button.dataset.sort === column).textContent.trim();
      section.querySelector('[data-sort-status]').textContent =
        `${label}, ${direction}. Minimum sample ${threshold}; smaller samples last.`;
    }
    buttons.forEach(button => button.addEventListener('click', () => {
      const next = button.dataset.sort;
      direction = next === column ? (direction === 'descending' ? 'ascending' : 'descending') :
        (next === 'player' ? 'ascending' : 'descending');
      column = next;
      render();
    }));
    refresh = render;
    render();
  });
})();
