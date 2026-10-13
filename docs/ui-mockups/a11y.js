/* Accessibility helpers shared by every mockup (dark pages load ../a11y.js), beside a11y.css.
 *
 * The pages build most of their rows, menus and dialogs from templates, so two rules are applied
 * here, once, to whatever is on the page -- and again whenever a script adds to it:
 *
 *   Names      a button or link that shows only an icon gets a spoken name: its title, or the
 *              icon's meaning (ICONS below). A field gets its label's text; a row's checkbox,
 *              "Select <row>"; a search box, its placeholder.
 *   Keyboard   whatever a mouse can click, Tab reaches and Enter or Space works -- rows, cards
 *              and chips with a click handler included.
 *
 * A name written in the page (aria-label, visible text) is never replaced. The web app does the
 * same in its components (Icon, Button, Input); this file exists because a mockup has none.
 */
(function () {
  // An icon-only control is named after what its icon means.
  var ICONS = {
    close: 'Close', more_vert: 'More actions', more_horiz: 'More actions', notifications: 'Notifications',
    help: 'Help', help_outline: 'Help', search: 'Search', add: 'Add', remove: 'Remove', delete: 'Delete',
    edit: 'Edit', content_copy: 'Copy', download: 'Download', upload: 'Upload', refresh: 'Refresh', sync: 'Update',
    settings: 'Settings', logout: 'Sign out', person: 'Account', account_circle: 'Account', info: 'Details',
    undo: 'Undo', redo: 'Redo', menu: 'Menu', menu_open: 'Menu', filter_list: 'Filter', tune: 'Filter',
    arrow_back: 'Back', arrow_forward: 'Next', arrow_upward: 'Up', arrow_downward: 'Down',
    chevron_left: 'Previous', chevron_right: 'Next', keyboard_arrow_right: 'Expand', keyboard_arrow_down: 'Collapse',
    keyboard_arrow_up: 'Collapse', expand_more: 'Expand', expand_less: 'Collapse', unfold_more: 'Expand', unfold_less: 'Collapse',
    left_panel_open: 'Show the panel', left_panel_close: 'Hide the panel', right_panel_open: 'Show the panel',
    right_panel_close: 'Hide the panel', open_in_full: 'Full size', close_fullscreen: 'Back to its size',
    open_in_new: 'Open in a new tab', zoom_in: 'Zoom in', zoom_out: 'Zoom out', fit_screen: 'Fit to the screen',
    visibility: 'Hide', visibility_off: 'Show', compare_arrows: 'Compare', history: 'History', terminal: 'Logs',
    light_mode: 'Switch to light theme', dark_mode: 'Switch to dark theme', clear_all: 'Clear', check: 'Confirm'
  };
  var FIELDS = 'input:not([type=hidden]), select, textarea';
  var NATIVE = { A: 1, BUTTON: 1, INPUT: 1, SELECT: 1, TEXTAREA: 1, LABEL: 1, SUMMARY: 1, OPTION: 1 };
  var INSIDE = 'a[href], button, input, select, textarea, [tabindex]';
  var AUTO = 'data-a11y-name';        // marks a name this file gave, so it can follow the icon when that changes

  function text(el) {
    var s = '';
    (function walk(n) {
      for (var c = n.firstChild; c; c = c.nextSibling) {
        if (c.nodeType === 3) s += c.nodeValue;
        else if (c.nodeType === 1 && c.getAttribute('aria-hidden') !== 'true' && c.tagName !== 'SCRIPT' && c.tagName !== 'STYLE') walk(c);
      }
    })(el);
    return s.replace(/\s+/g, ' ').trim();
  }
  function has(el, attr) { var v = el.getAttribute(attr); return !!(v && v.trim()); }
  function named(el) { return (has(el, 'aria-label') && !el.hasAttribute(AUTO)) || has(el, 'aria-labelledby'); }
  function setName(el, name) {
    if (!name) return;
    name = name.slice(0, 90);
    if (el.getAttribute('aria-label') !== name) el.setAttribute('aria-label', name);
    if (!el.hasAttribute(AUTO)) el.setAttribute(AUTO, '');
  }

  // ── Names: icon-only buttons and links ──────────────────────────────────────────────────────
  function nameControl(el) {
    if (named(el) || text(el)) return;
    if (has(el, 'title')) return setName(el, el.getAttribute('title').trim());
    var icon = el.querySelector('.material-symbols-outlined');
    if (!icon) return;
    var key = icon.textContent.trim();
    setName(el, ICONS[key] || (key.charAt(0).toUpperCase() + key.slice(1)).replace(/_/g, ' '));
  }

  // ── Names: fields ───────────────────────────────────────────────────────────────────────────
  function nameField(el) {
    if (named(el)) return;
    if (el.id && document.querySelector('label[for="' + (window.CSS && CSS.escape ? CSS.escape(el.id) : el.id) + '"]')) return;
    var wrap = el.closest('label');
    if (wrap && text(wrap)) return;
    if (el.type === 'checkbox' || el.type === 'radio') {
      var row = el.closest('tr, li, [class$="-row"], [class*="-row "]');
      var what = row ? text(row) : '';
      return setName(el, what ? 'Select ' + what : (has(el, 'title') ? el.getAttribute('title') : ''));
    }
    // the label written just above the field: the only one in the nearest block that holds one field
    for (var block = el.parentElement, hop = 0; block && hop < 3; block = block.parentElement, hop++) {
      if (block.querySelectorAll(FIELDS).length > 1) break;
      var label = block.querySelector('label, .lbl');
      if (label && text(label)) return setName(el, text(label).replace(/\s*\*$/, ''));
    }
    if (has(el, 'title')) return setName(el, el.getAttribute('title').trim());
    var ph = (el.getAttribute('placeholder') || '').trim();
    if (ph && !/^e\.g\./i.test(ph)) return setName(el, ph.replace(/[….]+$/, ''));
    if (el.type === 'file') setName(el, 'Choose a file');
  }

  // ── Keyboard: what a mouse can click, Tab reaches ───────────────────────────────────────────
  function reach(el) {
    if (NATIVE[el.tagName] && !(el.tagName === 'A' && !el.hasAttribute('href'))) return;
    if (el.hasAttribute('tabindex') || el.closest('label') || el.getAttribute('aria-hidden') === 'true') return;
    var on = el.getAttribute('onclick') || '';
    // not a control: a backdrop that closes its dialog, a wrapper that only stops a click, a box with nothing to read
    if (/event\.target\s*===?\s*this/.test(on) || /^\s*event\.stopPropagation\(\)\s*;?\s*$/.test(on)) return;
    if (!text(el) && !el.querySelector('.material-symbols-outlined, img') && !has(el, 'aria-label') && !has(el, 'title')) return;
    if (el.getAttribute('aria-disabled') === 'true') return;
    el.setAttribute('tabindex', '0');
    el.setAttribute('data-a11y-click', '');
    // a button, unless it is a table row or holds controls of its own (a card with buttons in it)
    if (!el.hasAttribute('role') && !/^(TR|TD|TH|LI|TBODY)$/.test(el.tagName) && !el.querySelector(INSIDE)) el.setAttribute('role', 'button');
  }
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var el = e.target;
    if (!el || !el.hasAttribute || !el.hasAttribute('data-a11y-click')) return;   // only the element itself, not a control inside it
    e.preventDefault();
    el.click();
  });

  function sweep(root) {
    if (!root.querySelectorAll) return;
    var list = root.querySelectorAll('[onclick]');
    for (var i = 0; i < list.length; i++) reach(list[i]);
    list = root.querySelectorAll('button, a[href], [role=button]');
    for (i = 0; i < list.length; i++) nameControl(list[i]);
    list = root.querySelectorAll(FIELDS);
    for (i = 0; i < list.length; i++) nameField(list[i]);
  }

  var pending = false;
  function later() {
    if (pending) return;
    pending = true;
    setTimeout(function () { pending = false; sweep(document.body); }, 60);
  }
  function start() {
    sweep(document.body);
    new MutationObserver(function (changes) {
      for (var i = 0; i < changes.length; i++) {
        var c = changes[i];
        // our own attribute writes must not start another sweep
        if (c.type === 'attributes') continue;
        return later();
      }
    }).observe(document.body, { childList: true, subtree: true, characterData: true });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
