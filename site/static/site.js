// Currency switch (USD default, EUR on demand) + lazy lava.top widgets + sticky buy bar.
(function () {
  var root = document.documentElement;
  var KEY = 'hush_cur';

  function store(v) { try { if (v) localStorage.setItem(KEY, v); return localStorage.getItem(KEY); } catch (e) { return null; } }

  function apply(cur) {
    if (cur !== 'USD' && cur !== 'EUR') cur = root.getAttribute('data-default-cur') || 'USD';
    root.setAttribute('data-cur', cur);
    document.querySelectorAll('[data-set-cur]').forEach(function (b) {
      b.setAttribute('aria-pressed', b.getAttribute('data-set-cur') === cur ? 'true' : 'false');
    });
    // load only the widget for the chosen currency
    document.querySelectorAll('.only-' + cur.toLowerCase() + ' iframe[data-src]').forEach(function (f) {
      if (!f.getAttribute('src')) f.setAttribute('src', f.getAttribute('data-src'));
    });
  }

  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-set-cur]');
    if (!b) return;
    var cur = b.getAttribute('data-set-cur');
    store(cur);
    apply(cur);
  });

  apply(store(null));

  // sticky buy bar: show on phones while the payment block is off screen
  var bar = document.getElementById('buybar');
  var buy = document.getElementById('buy');
  if (bar && buy && 'IntersectionObserver' in window) {
    bar.hidden = false;
    document.body.classList.add('has-bar');
    var hero = document.querySelector('.hero');
    var seen = { buy: false, hero: true };
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) { seen[en.target === buy ? 'buy' : 'hero'] = en.isIntersecting; });
      bar.style.display = (seen.buy || seen.hero) ? 'none' : '';
    });
    io.observe(buy);
    if (hero) io.observe(hero); else seen.hero = false;
  }
})();
