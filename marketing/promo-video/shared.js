// Fills [data-p="key"] from config.js, draws the logo glyph, and lets render.js seek every animation.
(function () {
  const P = window.PROMO || {};
  const LOGO = '<svg viewBox="0 0 24 24" fill="#fff"><rect x="2" y="3" width="8" height="6" rx="1.5"/>' +
    '<rect x="14" y="9" width="8" height="6" rx="1.5"/><rect x="14" y="17" width="8" height="5" rx="1.5"/>' +
    '<path d="M6 9v10h8M6 12h8" stroke="#fff" stroke-width="2" fill="none"/></svg>';

  function fill() {
    document.querySelectorAll("[data-p]").forEach((el) => { el.textContent = P[el.dataset.p] ?? ""; });
    document.querySelectorAll(".logo").forEach((el) => { el.innerHTML = LOGO; });
  }

  window.__seek = (ms) => {
    document.getAnimations().forEach((a) => { a.pause(); a.currentTime = ms; });
  };
  // Rendering (?render): hold at 0 and wait to be sought. Opened by hand: play normally, so it can be
  // screen-recorded too.
  const rendering = /[?&]render/.test(location.search);
  window.__ready = new Promise((resolve) => {
    window.addEventListener("load", () => {
      fill();
      document.fonts.ready.then(() => requestAnimationFrame(() => {
        if (rendering) window.__seek(0);
        resolve(true);
      }));
    });
  });
})();
