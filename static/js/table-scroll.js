/* Measure all tables together after deferred scripts/layout, then apply edge states. */
(() => {
  const initialize = () => {
    const tables = [];
    let pending = false;
    const measure = () => {
      pending = false;
      // Complete every layout read before changing any classes, including across tables.
      const states = tables.map(({scroll, frame}) => {
        const vertical = scroll.scrollHeight - scroll.clientHeight;
        const horizontal = scroll.scrollWidth - scroll.clientWidth;
        return {frame, edges: {
          top: vertical > 1 && scroll.scrollTop > 0,
          bottom: vertical > 1 && vertical - scroll.scrollTop > 1,
          left: horizontal > 1 && scroll.scrollLeft > 0,
          right: horizontal > 1 && horizontal - scroll.scrollLeft > 1
        }};
      });
      for (const {frame, edges} of states) {
        for (const [edge, visible] of Object.entries(edges)) {
          frame.classList.toggle(`more-${edge}`, visible);
        }
      }
    };
    const schedule = () => {
      if (pending) return;
      pending = true;
      requestAnimationFrame(measure);
    };
    const resize = new ResizeObserver(schedule);
    const content = new MutationObserver(schedule);
    document.querySelectorAll('.statistics-scroll').forEach(scroll => {
      const frame = document.createElement('div'); frame.className = 'table-scroll-frame';
      scroll.before(frame); frame.append(scroll);
      for (const edge of ['top', 'bottom', 'left', 'right']) {
        const shade = document.createElement('span');
        shade.className = `scroll-edge scroll-edge-${edge}`;
        shade.setAttribute('aria-hidden', 'true'); frame.append(shade);
      }
      tables.push({scroll, frame});
      scroll.addEventListener('scroll', schedule, {passive: true});
      resize.observe(scroll);
      if (scroll.firstElementChild) resize.observe(scroll.firstElementChild);
      content.observe(scroll, {childList: true, subtree: true, characterData: true});
    });
    if (!tables.length) return;
    schedule();
    window.addEventListener('load', schedule, {once: true});
    window.addEventListener('pageshow', schedule);
    document.fonts?.ready.then(schedule);
  };
  // A deferred script runs in the interactive state before DOMContentLoaded.
  // Wait for the other deferred enhancements (including row sorting) as well.
  if (document.readyState !== 'complete') {
    document.addEventListener('DOMContentLoaded', initialize, {once: true});
  } else initialize();
})();
