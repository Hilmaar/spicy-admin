/* UTC-only, progressive enhancement. The server remains the validation authority. */
(() => {
  const dialog = document.querySelector('#mining-range-dialog');
  if (!dialog || typeof dialog.showModal !== 'function' || !window.MiningClock) return;
  const form = document.querySelector('.analytics-filters');
  const preset = form.querySelector('#id_range');
  const startInput = form.querySelector('#id_start');
  const endInput = form.querySelector('#id_end');
  const openButton = form.querySelector('[data-range-open]');
  const calendar = dialog.querySelector('[data-calendar]');
  const exactStart = dialog.querySelector('#precise-start');
  const exactEnd = dialog.querySelector('#precise-end');
  const error = dialog.querySelector('[data-range-error]');
  const mobile = matchMedia('(max-width: 650px)');
  const dayMS = 86400000;
  const today = new Date().toISOString().slice(0, 10);
  const date = (iso) => new Date(`${iso}T00:00:00Z`);
  const iso = (value) => value.toISOString().slice(0, 10);
  const addDays = (value, days) => iso(new Date(date(value).getTime() + days * dayMS));
  const monthName = (value) => value.toLocaleDateString('en-GB', {
    month: 'long', year: 'numeric', timeZone: 'UTC'
  });
  // ISO dates, naive ISO timestamps (UTC), and explicit offsets; no locale parsing.
  const parse = (value) => {
    if (!/^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?)?$/.test(value)) return null;
    const rawDay = value.slice(0, 10);
    const d = date(rawDay);
    if (Number.isNaN(d.getTime()) || iso(d) !== rawDay) return null;
    let normalized = value.replace(' ', 'T');
    if (value.length === 10) normalized += 'T00:00:00Z';
    else if (!/(Z|[+-]\d{2}:\d{2})$/.test(value)) normalized += 'Z';
    const parsed = new Date(normalized);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  };
  let first = null, last = null, hover = null, selectingEnd = false;
  let wholeEnd = true;
  const friendly = (raw) => {
    const value = parse(raw);
    return value ? value.toLocaleString('en-GB', {
      day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
      second: '2-digit', timeZone: 'UTC', hourCycle: 'h23'
    }) : '';
  };
  const timeText = (raw, fallback) => {
    const value = parse(raw);
    return value ? value.toISOString().slice(11, 16) : fallback;
  };
  const updateTimes = () => {
    dialog.querySelector('#start-time-value').textContent = timeText(exactStart.value, '00:00');
    dialog.querySelector('#end-time-value').textContent = wholeEnd ? '23:59' : timeText(exactEnd.value, '23:59');
    dialog.querySelector('[data-end-time-note]').textContent = wholeEnd ?
      'End of day (includes the entire final date)' : `Exclusive end on ${last || 'the selected end date'}`;
  };
  let month = date(`${today.slice(0, 7)}-01`), focusDay = today;
  const make = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const paint = () => {
    const endpoint = selectingEnd ? hover : last;
    const low = first && endpoint ? [first, endpoint].sort()[0] : first;
    const high = first && endpoint ? [first, endpoint].sort()[1] : first;
    calendar.querySelectorAll('[data-day]').forEach((button) => {
      const value = button.dataset.day;
      button.classList.toggle('in-range', Boolean(low && high && value >= low && value <= high));
      button.classList.toggle('range-endpoint', value === first || (!selectingEnd && value === last));
      button.classList.toggle('range-preview', Boolean(selectingEnd && endpoint && value >= low && value <= high));
      button.setAttribute('aria-pressed', String(Boolean(!selectingEnd && low && value >= low && value <= high)));
    });
  };
  const describe = () => {
    dialog.querySelector('[data-selection]').textContent = !first ? 'Choose a start date.' :
      selectingEnd ? `${first} selected. Choose an end date.` :
        `${first} 00:00 through ${last} 23:59:59 UTC (whole dates).`;
  };
  const choose = (value) => {
    error.textContent = '';
    wholeEnd = true;
    if (!selectingEnd) {
      first = value; last = null; hover = null; selectingEnd = true;
      exactStart.value = `${first}T00:00:00Z`; exactEnd.value = '';
    } else {
      [first, last] = [first, value].sort(); selectingEnd = false; hover = null;
      exactStart.value = `${first}T00:00:00Z`;
      exactEnd.value = `${addDays(last, 1)}T00:00:00Z`;
    }
    describe(); paint(); updateTimes();
  };
  const render = () => {
    calendar.replaceChildren();
    const count = mobile.matches ? 1 : 2;
    const endMonth = new Date(Date.UTC(month.getUTCFullYear(), month.getUTCMonth() + count - 1, 1));
    dialog.querySelector('[data-month-label]').textContent = count === 1 ? monthName(month) :
      `${monthName(month)} – ${monthName(endMonth)}`;
    for (let offset = 0; offset < count; offset++) {
      const current = new Date(Date.UTC(month.getUTCFullYear(), month.getUTCMonth() + offset, 1));
      const section = make('section', 'calendar-month');
      section.setAttribute('aria-label', monthName(current));
      section.append(make('h3', '', monthName(current)));
      const grid = make('div', 'calendar-grid');
      ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'].forEach((day) => {
        const label = make('span', 'calendar-weekday', day); label.setAttribute('aria-hidden', 'true'); grid.append(label);
      });
      const blanks = (current.getUTCDay() + 6) % 7;
      for (let i = 0; i < blanks; i++) grid.append(make('span'));
      const days = new Date(Date.UTC(current.getUTCFullYear(), current.getUTCMonth() + 1, 0)).getUTCDate();
      for (let day = 1; day <= days; day++) {
        const value = iso(new Date(Date.UTC(current.getUTCFullYear(), current.getUTCMonth(), day)));
        const button = make('button', 'calendar-day', String(day));
        button.type = 'button'; button.dataset.day = value;
        button.tabIndex = value === focusDay ? 0 : -1;
        button.setAttribute('aria-label', value);
        if (value === today) { button.classList.add('is-today'); button.setAttribute('aria-current', 'date'); }
        button.addEventListener('click', () => { focusDay = value; choose(value); });
        button.addEventListener('pointerenter', () => { if (selectingEnd) { hover = value; paint(); } });
        button.addEventListener('focus', () => {
          focusDay = value;
          calendar.querySelectorAll('[data-day]').forEach((b) => { b.tabIndex = b === button ? 0 : -1; });
          if (selectingEnd) { hover = value; paint(); }
        });
        button.addEventListener('keydown', (event) => {
          const shift = {ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7};
          let next;
          if (event.key in shift) next = addDays(value, shift[event.key]);
          else if (event.key === 'Home') next = addDays(value, -((date(value).getUTCDay() + 6) % 7));
          else if (event.key === 'End') next = addDays(value, 6 - ((date(value).getUTCDay() + 6) % 7));
          else if (event.key === 'PageUp' || event.key === 'PageDown') {
            const d = date(value), step = event.key === 'PageUp' ? -1 : 1;
            const max = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + step + 1, 0)).getUTCDate();
            next = iso(new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + step, Math.min(d.getUTCDate(), max))));
          }
          if (!next) return;
          event.preventDefault(); focusDay = next;
          if (!calendar.querySelector(`[data-day="${next}"]`)) month = date(`${next.slice(0, 7)}-01`);
          render(); calendar.querySelector(`[data-day="${next}"]`)?.focus();
        });
        grid.append(button);
      }
      section.append(grid); calendar.append(section);
    }
    if (!calendar.querySelector('[tabindex="0"]')) {
      const button = calendar.querySelector('[data-day]'); button.tabIndex = 0; focusDay = button.dataset.day;
    }
    paint();
  };
  const updateSummary = () => {
    form.querySelector('[data-range-summary]').textContent = preset.value === 'custom' && startInput.value && endInput.value ?
      `${friendly(startInput.value)} to ${friendly(endInput.value)} UTC (end exclusive)` : 'Select both dates in one calendar. UTC, inclusive whole dates.';
  };
  const open = () => {
    exactStart.value = startInput.value; exactEnd.value = endInput.value;
    const start = parse(startInput.value), end = parse(endInput.value);
    wholeEnd = !end || (end.toISOString().slice(11) === '00:00:00.000Z' &&
      !/\.\d*[1-9]/.test(endInput.value));
    first = start ? iso(start) : null;
    last = end ? iso(wholeEnd ? new Date(end.getTime() - 1) : end) : null;
    selectingEnd = false; hover = null; error.textContent = '';
    focusDay = first || today; month = date(`${focusDay.slice(0, 7)}-01`);
    dialog.querySelector('details').open = false;
    render(); describe(); updateTimes();
    if (start && end) dialog.querySelector('[data-selection]').textContent =
      `${friendly(startInput.value)} to ${friendly(endInput.value)} UTC (end exclusive)`;
    dialog.showModal(); calendar.querySelector('[tabindex="0"]')?.focus();
  };
  openButton.addEventListener('click', open);
  dialog.querySelectorAll('[data-range-cancel]').forEach((b) => b.addEventListener('click', () => dialog.close()));
  dialog.addEventListener('close', () => openButton.focus());
  // Native dialog Escape cancellation restores committed inputs unchanged.
  for (const [selector, step] of [['[data-month-prev]', -1], ['[data-month-next]', 1]]) {
    dialog.querySelector(selector).addEventListener('click', () => {
      month = new Date(Date.UTC(month.getUTCFullYear(), month.getUTCMonth() + step, 1)); render();
    });
  }
  calendar.addEventListener('pointerleave', () => { hover = null; paint(); });
  for (const [selector, isEnd] of [['[data-time-start]', false], ['[data-time-end]', true]]) {
    const button = dialog.querySelector(selector);
    button.addEventListener('click', () => {
      if (!first || !last || selectingEnd) {
        error.textContent = 'Choose both dates before adjusting times.'; return;
      }
      const field = isEnd ? exactEnd : exactStart;
      const time = isEnd && wholeEnd ? '23:59' : timeText(field.value, '00:00');
      window.MiningClock.open(button, time, (selected) => {
        field.value = `${isEnd ? last : first}T${selected}:00Z`;
        if (isEnd) wholeEnd = false;
        error.textContent = ''; updateTimes();
        dialog.querySelector('[data-selection]').textContent =
          `${friendly(exactStart.value)} to ${friendly(exactEnd.value)} UTC (end exclusive)`;
      });
    });
  }
  dialog.querySelector('[data-end-whole]').addEventListener('click', () => {
    if (!last || selectingEnd) return;
    wholeEnd = true; exactEnd.value = `${addDays(last, 1)}T00:00:00Z`;
    updateTimes();
    dialog.querySelector('[data-selection]').textContent =
      `${friendly(exactStart.value)} to ${friendly(exactEnd.value)} UTC (end exclusive)`;
  });
  dialog.querySelector('[data-range-apply]').addEventListener('click', () => {
    const start = parse(exactStart.value), end = parse(exactEnd.value);
    // Date compares milliseconds; finer precision is validated by Django, not rounded here.
    if (selectingEnd || !start || !end || start > end || exactStart.value === exactEnd.value) {
      error.textContent = 'Choose a complete range with an end after its start, or enter valid precise UTC bounds.'; return;
    }
    // Preserve exact submitted text, including subsecond precision; server normalizes UTC.
    startInput.value = exactStart.value; endInput.value = exactEnd.value; preset.value = 'custom';
    updateSummary(); dialog.close(); form.requestSubmit();
  });
  preset.addEventListener('change', () => {
    if (preset.value !== 'custom') { startInput.value = ''; endInput.value = ''; }
    updateSummary();
  });
  mobile.addEventListener('change', () => { if (dialog.open) render(); });
  form.querySelectorAll('.exact-fallback').forEach((field) => {
    field.hidden = !field.querySelector('.errorlist');
  });
  form.querySelector('.range-picker-control').hidden = false;
  updateSummary();
})();
