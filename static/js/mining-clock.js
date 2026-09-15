/* A draft-only clock: Use time commits to the calendar, never submits the report. */
(() => {
  const dialog = document.querySelector('#mining-clock-dialog');
  if (!dialog || typeof dialog.showModal !== 'function') return;
  const face = dialog.querySelector('.clock-face');
  const numbers = dialog.querySelector('[data-clock-numbers]');
  const hours = dialog.querySelector('[data-clock-hours]');
  const minutes = dialog.querySelector('[data-clock-minutes]');
  const pad = (n) => String(n).padStart(2, '0');
  let hour = 0, minute = 0, stage = 'hour', opener, commit;
  const render = () => {
    hours.textContent = pad(hour); minutes.textContent = pad(minute);
    hours.setAttribute('aria-pressed', String(stage === 'hour'));
    minutes.setAttribute('aria-pressed', String(stage === 'minute'));
    const value = stage === 'hour' ? hour : minute;
    face.setAttribute('aria-label', stage === 'hour' ? 'Hour' : 'Minute');
    face.setAttribute('aria-valuemax', stage === 'hour' ? '23' : '59');
    face.setAttribute('aria-valuenow', value);
    face.setAttribute('aria-valuetext', `${pad(value)} ${stage}`);
    dialog.querySelector('[data-clock-status]').textContent = stage === 'hour' ?
      'Hours: outer ring 1–12, inner ring 13–23 and 00.' : 'Minutes: choose any minute, 00–59.';
    numbers.replaceChildren();
    const count = stage === 'hour' ? 24 : 60;
    for (let n = 0; n < count; n++) {
      const inner = stage === 'hour' && (n === 0 || n > 12);
      const radius = inner ? 76 : 116;
      const angle = n * Math.PI / (stage === 'hour' ? 6 : 30);
      const button = document.createElement('button');
      button.type = 'button'; button.tabIndex = -1;
      button.className = 'clock-number';
      button.dataset.value = n;
      button.classList.toggle('selected', n === value);
      button.classList.toggle('clock-dot', stage === 'minute' && n % 5 !== 0);
      button.textContent = stage === 'hour' || n % 5 === 0 || n === value ? pad(n) : '·';
      button.setAttribute('aria-label', `${stage} ${pad(n)}`);
      button.style.left = `${(140 + Math.sin(angle) * radius) / 2.8}%`;
      button.style.top = `${(140 - Math.cos(angle) * radius) / 2.8}%`;
      button.addEventListener('click', () => select(n));
      numbers.append(button);
    }
    const angle = value * Math.PI / (stage === 'hour' ? 6 : 30);
    const radius = stage === 'hour' && (hour === 0 || hour > 12) ? 76 : 116;
    const hand = face.querySelector('line');
    hand.setAttribute('x2', 140 + Math.sin(angle) * radius);
    hand.setAttribute('y2', 140 - Math.cos(angle) * radius);
  };
  const select = (value) => {
    if (stage === 'hour') { hour = value; stage = 'minute'; }
    else minute = value;
    render(); face.focus();
  };
  // Clicking between labels still picks the nearest minute/hour, including touch taps.
  face.addEventListener('click', (event) => {
    if (event.target.closest('button')) return;
    const box = face.getBoundingClientRect();
    const x = (event.clientX - box.left) * 280 / box.width - 140;
    const y = (event.clientY - box.top) * 280 / box.height - 140;
    const angle = (Math.atan2(x, -y) + Math.PI * 2) % (Math.PI * 2);
    if (stage === 'minute') select(Math.round(angle * 30 / Math.PI) % 60);
    else {
      const position = Math.round(angle * 6 / Math.PI) % 12;
      select(Math.hypot(x, y) < 96 ? (position === 0 ? 0 : position + 12) : (position || 12));
    }
  });
  face.addEventListener('keydown', (event) => {
    const count = stage === 'hour' ? 24 : 60;
    let value = stage === 'hour' ? hour : minute;
    if (['ArrowRight', 'ArrowUp'].includes(event.key)) value = (value + 1) % count;
    else if (['ArrowLeft', 'ArrowDown'].includes(event.key)) value = (value + count - 1) % count;
    else if (event.key === 'Home') value = 0;
    else if (event.key === 'End') value = count - 1;
    else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      if (stage === 'hour') select(hour);
      else dialog.querySelector('[data-clock-save]').focus();
      return;
    } else return;
    event.preventDefault();
    if (stage === 'hour') hour = value; else minute = value;
    render();
  });
  hours.addEventListener('click', () => { stage = 'hour'; render(); face.focus(); });
  minutes.addEventListener('click', () => { stage = 'minute'; render(); face.focus(); });
  dialog.querySelector('[data-clock-cancel]').addEventListener('click', () => dialog.close());
  dialog.querySelector('[data-clock-save]').addEventListener('click', () => {
    commit(pad(hour) + ':' + pad(minute)); dialog.close();
  });
  dialog.addEventListener('close', () => opener?.focus());
  window.MiningClock = {
    open(button, time, onCommit) {
      opener = button; commit = onCommit;
      [hour, minute] = time.split(':').map(Number);
      stage = 'hour'; render(); dialog.showModal(); face.focus();
    }
  };
})();
