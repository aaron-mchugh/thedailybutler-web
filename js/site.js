// The Daily Butler — site JS (newsletter form, archive search, mobile nav)
(function () {
  "use strict";

  // ---------- mobile nav toggle ----------
  var navToggle = document.querySelector('[data-nav-toggle]');
  var navLinks = document.querySelector('.nav-links');
  if (navToggle && navLinks) {
    navToggle.addEventListener('click', function () {
      navLinks.classList.toggle('open');
    });
  }

  // ---------- newsletter form (POSTs to /api/subscribe) ----------
  document.querySelectorAll('form[data-newsletter]').forEach(function (form) {
    var status = form.querySelector('[data-status]');
    var input = form.querySelector('input[type=email]');
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var email = (input.value || '').trim();
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
        if (status) { status.textContent = 'Please enter a valid email.'; status.className = 'err'; }
        return;
      }
      if (status) { status.textContent = 'Subscribing…'; status.className = 'muted'; }
      var btn = form.querySelector('button');
      if (btn) btn.disabled = true;
      fetch('/api/subscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email })
      }).then(function (r) {
        return r.json().catch(function () { return {}; });
      }).then(function (d) {
        if (status) {
          if (d.ok) { status.textContent = 'Subscribed — see you each morning.'; status.className = 'ok'; }
          else { status.textContent = d.message || 'Something went wrong. Try again.'; status.className = 'err'; }
        }
        if (d.ok && input) input.value = '';
      }).catch(function () {
        if (status) { status.textContent = 'Could not reach the server. Try again.'; status.className = 'err'; }
      }).finally(function () { if (btn) btn.disabled = false; });
    });
  });

  // ---------- archive search / filter (client-side, no backend) ----------
  var searchInput = document.querySelector('[data-archive-search]');
  var monthSelect = document.querySelector('[data-archive-month]');
  var cards = Array.prototype.slice.call(document.querySelectorAll('[data-ep-card]'));
  var countEl = document.querySelector('[data-archive-count]');

  function applyFilter() {
    var q = (searchInput.value || '').toLowerCase().trim();
    var month = monthSelect ? monthSelect.value : '';
    var shown = 0;
    cards.forEach(function (c) {
      var hay = (c.getAttribute('data-q') || '').toLowerCase();
      var mOk = !month || (c.getAttribute('data-month') === month);
      var qOk = !q || hay.indexOf(q) !== -1;
      var show = mOk && qOk;
      c.classList.toggle('hidden', !show);
      if (show) shown++;
    });
    if (countEl) {
      countEl.textContent = q || month
        ? shown + ' episode' + (shown === 1 ? '' : 's')
        : '';
    }
  }
  if (searchInput) { searchInput.addEventListener('input', applyFilter); }
  if (monthSelect) { monthSelect.addEventListener('change', applyFilter); }
})();
