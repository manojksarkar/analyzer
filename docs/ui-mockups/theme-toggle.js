/* Light/dark toggle for the UI mockups.
 *
 * Each mockup exists twice: docs/ui-mockups/<page>.html (light) and
 * docs/ui-mockups/dark/<page>.html (dark). The toggle swaps to the counterpart
 * file and remembers the choice, so following a link keeps the chosen theme.
 * Load it in <head> (no defer) so a page in the wrong theme is swapped before it paints.
 */
(function () {
  var KEY = 'mockupTheme';
  var path = location.pathname;
  var isDark = /\/dark\/[^\/]*$/.test(path);
  var current = isDark ? 'dark' : 'light';

  function counterpart() {
    var url = isDark ? path.replace(/\/dark\/([^\/]*)$/, '/$1') : path.replace(/\/([^\/]*)$/, '/dark/$1');
    return url + location.search + location.hash;
  }

  function read() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }

  function write(value) {
    try { localStorage.setItem(KEY, value); } catch (e) { /* storage blocked: the toggle still navigates */ }
  }

  var saved = read();
  if (saved && saved !== current) {
    location.replace(counterpart());
    return;
  }

  function toggle() {
    write(isDark ? 'light' : 'dark');
    location.href = counterpart();
  }

  function mount() {
    var label = isDark ? 'Switch to light theme' : 'Switch to dark theme';
    var icon = isDark ? 'light_mode' : 'dark_mode';
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.id = 'theme-toggle';
    btn.title = label;
    btn.setAttribute('aria-label', label);
    btn.innerHTML = '<span class="material-symbols-outlined text-on-surface-variant" style="font-size:22px;">' + icon + '</span>';
    btn.addEventListener('click', toggle);

    // In the header: first of the right-hand actions. No header (sign-in): float top-right.
    var header = document.querySelector('header');
    var actions = header && header.lastElementChild;
    if (actions && actions !== header.firstElementChild) {
      btn.className = 'relative p-2 hover:bg-surface-container rounded-lg transition-colors';
      actions.insertBefore(btn, actions.firstChild);
    } else {
      btn.className = 'p-2 rounded-full border border-outline-variant bg-surface-container-lowest hover:bg-surface-container transition-colors';
      btn.style.cssText = 'position:fixed;top:16px;right:16px;z-index:200;display:flex;';
      document.body.appendChild(btn);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }
})();
