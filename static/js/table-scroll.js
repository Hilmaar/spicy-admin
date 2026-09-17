/* Passive edge affordances; table content and sticky headers remain untouched. */
(() => {
  document.querySelectorAll('.statistics-scroll').forEach(scroll => {
    const frame = document.createElement('div'); frame.className = 'table-scroll-frame';
    scroll.before(frame); frame.append(scroll);
    for (const edge of ['top', 'bottom', 'left', 'right']) {
      const shade = document.createElement('span');
      shade.className = `scroll-edge scroll-edge-${edge}`;
      shade.setAttribute('aria-hidden', 'true'); frame.append(shade);
    }
    const update = () => {
      frame.classList.toggle('more-top', scroll.scrollTop > 1);
      frame.classList.toggle('more-bottom', scroll.scrollHeight - scroll.clientHeight - scroll.scrollTop > 1);
      frame.classList.toggle('more-left', scroll.scrollLeft > 1);
      frame.classList.toggle('more-right', scroll.scrollWidth - scroll.clientWidth - scroll.scrollLeft > 1);
    };
    scroll.addEventListener('scroll', update, {passive: true});
    const observer = new ResizeObserver(update); observer.observe(scroll);
    if (scroll.firstElementChild) observer.observe(scroll.firstElementChild);
    new MutationObserver(update).observe(scroll, {childList: true, subtree: true});
    update();
  });
})();
