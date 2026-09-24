/* Portfolio Analyzer — moteur d'effets (sections 1 · 6 · 9). Aucune dépendance. */
(() => {
  const root = document.documentElement;
  root.classList.add('js');

  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const touch = matchMedia('(hover: none)').matches;
  const $ = (s, c = document) => c.querySelector(s);
  const $$ = (s, c = document) => [...c.querySelectorAll(s)];
  const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
  const lerp = (a, b, t) => a + (b - a) * t;
  const GLYPHS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789$€%#£&*+';

  // date du jour dans le badge
  const MOIS = ['JANV', 'FÉVR', 'MARS', 'AVR', 'MAI', 'JUIN', 'JUIL', 'AOÛT', 'SEPT', 'OCT', 'NOV', 'DÉC'];
  const now = new Date();
  $('#today').textContent = `${now.getDate()} ${MOIS[now.getMonth()]} ${now.getFullYear()}`;

  /* ───────── décodage de texte (réf. Locomotive) ───────── */
  function decode(el, text, { duration = 900, delay = 0, wrapScr = false } = {}) {
    return new Promise(res => {
      const start = performance.now() + delay;
      const chars = [...text];
      (function frame(t) {
        const p = clamp((t - start) / duration);
        if (t < start) { requestAnimationFrame(frame); return; }
        const shown = Math.floor(p * chars.length * 1.15);
        let out = '';
        chars.forEach((c, i) => {
          if (c === ' ' || c === ' ') out += c;
          else if (i < shown - 2) out += c;
          else out += wrapScr ? `<span class="scr">${GLYPHS[(Math.random() * GLYPHS.length) | 0]}</span>` : GLYPHS[(Math.random() * GLYPHS.length) | 0];
        });
        if (wrapScr) el.innerHTML = out; else el.textContent = out;
        if (p < 1) requestAnimationFrame(frame);
        else { if (wrapScr) el.textContent = text; else el.textContent = text; res(); }
      })(performance.now());
    });
  }

  /* ───────── compteurs ───────── */
  function fmt(v, dec, prefix = '', suffix = '') {
    const s = v.toLocaleString('fr-FR', { minimumFractionDigits: dec, maximumFractionDigits: dec }).replace(/ /g, ' ');
    return prefix + s + suffix;
  }
  function count(el, dur = 1800, delay = 0) {
    const to = parseFloat(el.dataset.count), dec = +(el.dataset.dec || 0);
    const prefix = el.dataset.prefix || '', suffix = el.dataset.suffix || '';
    if (reduced) { el.textContent = fmt(to, dec, prefix, suffix); return; }
    const t0 = performance.now() + delay;
    (function f(t) {
      const p = clamp((t - t0) / dur);
      const e = 1 - Math.pow(1 - p, 4);
      el.textContent = fmt(to * e, dec, prefix, suffix);
      if (p < 1) requestAnimationFrame(f);
    })(performance.now());
  }

  /* ───────── découpes de texte ───────── */
  // hero : masque + mot à mot
  let wi = 0;
  $$('#heroTitle .line').forEach(line => {
    const words = line.textContent.trim().split(/\s+/);
    line.setAttribute('aria-label', line.textContent.trim());
    line.innerHTML = words.map(w => `<span class="w" aria-hidden="true"><span style="--i:${wi++}">${w}</span></span>`).join(' ');
  });
  // backtest : mot > caractères
  const quote = $('#btQuote');
  quote.setAttribute('aria-label', quote.textContent.trim());
  quote.innerHTML = quote.textContent.trim().split(/\s+/)
    .map(w => `<span class="wd" aria-hidden="true">${[...w].map(c => `<span class="ch">${c}</span>`).join('')}</span>`).join(' ');
  const chars = $$('.ch', quote);
  // footer : lettres
  $$('[data-letters]').forEach(el => {
    el.innerHTML = [...el.textContent].map((c, i) => `<span class="l" style="--k:${i}">${c === ' ' ? '&nbsp;' : c}</span>`).join('');
  });

  /* ───────── LOADER puis entrée du hero ───────── */
  const loader = $('#loader'), bar = $('#loaderBar'), pct = $('#loaderPct'), word = $('#loaderWord');

  function ready() {
    document.body.classList.add('ready');
    loader.classList.add('done');
    $$('[data-count]', $('#card3d')).forEach((el, i) => count(el, 1900, 900 + i * 120));
    setTimeout(() => loader.remove(), 1000);
  }

  if (reduced) {
    loader.remove();
    document.body.classList.add('ready');
    $$('[data-count]').forEach(el => count(el));
    $$('[data-in]').forEach(el => el.classList.add('in'));
    chars.forEach(c => c.classList.add('on'));
    $('#btGlyph').classList.add('in'); $('#btSign').classList.add('in'); $('#btRule').style.transform = 'none';
    $('#footWord').classList.add('in');
  } else {
    $$('[data-decode]', loader).forEach((el, i) => decode(el, el.dataset.decode, { duration: 1300, delay: 150 + i * 200 }));
    // "Portfolio " en clair, "Analyzer" se résout en scramble
    const finalWord = 'Portfolio Analyzer';
    decode(word, finalWord, { duration: 1100, delay: 100, wrapScr: true });
    const t0 = performance.now(), D = 1500;
    (function tick(t) {
      const p = clamp((t - t0) / D);
      const e = 1 - Math.pow(1 - p, 3);
      bar.style.transform = `scaleX(${e})`;
      pct.textContent = Math.round(e * 100) + '%';
      if (p < 1) requestAnimationFrame(tick); else setTimeout(ready, 250);
    })(t0);
  }

  /* ───────── IntersectionObserver : reveals au scroll ───────── */
  const io = new IntersectionObserver(es => es.forEach(e => {
    if (!e.isIntersecting) return;
    e.target.classList.add('in'); io.unobserve(e.target);
  }), { threshold: .25 });
  $$('.footer [data-in]').forEach(el => io.observe(el));
  io.observe($('#footWord'));

  /* ───────── curseur + magnétisme ───────── */
  const cursor = $('#cursor');
  let mx = innerWidth / 2, my = innerHeight / 2, cx = mx, cy = my;
  if (!touch) {
    addEventListener('pointermove', e => { mx = e.clientX; my = e.clientY; cursor.classList.add('on'); });
    document.addEventListener('pointerover', e => cursor.classList.toggle('big', !!e.target.closest('a, button, .btn')));
  }
  $$('.mag').forEach(el => {
    el.addEventListener('pointermove', e => {
      const r = el.getBoundingClientRect();
      el.style.transform = `translate(${(e.clientX - r.left - r.width / 2) * .25}px, ${(e.clientY - r.top - r.height / 2) * .35}px)`;
    });
    el.addEventListener('pointerleave', () => { el.style.transition = 'transform .6s cubic-bezier(.19,1,.22,1), background .35s, color .35s, border-color .35s'; el.style.transform = ''; setTimeout(() => el.style.transition = '', 600); });
  });

  /* décodage au survol (liens du footer) */
  $$('[data-decode-hover]').forEach(el => {
    el.addEventListener('pointerenter', () => decode(el, el.dataset.decodeHover, { duration: 420 }));
  });

  /* ───────── boucle : parallax souris, tilt 3D, scrub scroll ───────── */
  const stage = $('#stage'), card = $('#card3d'), chips = $$('.chip', stage);
  let tiltX = 0, tiltY = 0, tX = 0, tY = 0;   // cibles/valeurs lissées de l'inclinaison
  let pX = 0, pY = 0, qX = 0, qY = 0;         // parallax chips
  let hot = false;

  card.addEventListener('pointerenter', () => { hot = true; card.classList.add('hot'); });
  card.addEventListener('pointerleave', () => { hot = false; card.classList.remove('hot'); });
  card.addEventListener('pointermove', e => {
    const r = card.getBoundingClientRect();
    card.style.setProperty('--gx', (e.clientX - r.left) + 'px');
    card.style.setProperty('--gy', (e.clientY - r.top) + 'px');
  });

  const bt = $('.backtest'), btGlyph = $('#btGlyph'), btRule = $('#btRule'), btSign = $('#btSign'), btFig = $('#btFig');
  let figDone = false;

  function loop() {
    const vw = innerWidth, vh = innerHeight;

    // curseur lissé
    cx = lerp(cx, mx, .2); cy = lerp(cy, my, .2);
    cursor.style.transform = `translate(${cx}px, ${cy}px)`;

    // hero : inclinaison + parallax
    const nx = (mx / vw - .5), ny = (my / vh - .5);
    const sr = stage.getBoundingClientRect();
    const lift = clamp(1 - (sr.top - vh * .1) / vh, 0, 1);     // 0 → 1 quand l'objet monte dans le cadre
    tX = hot ? -(((my - card.getBoundingClientRect().top) / card.offsetHeight) - .5) * 7 : ny * -2;
    tY = hot ? (((mx - card.getBoundingClientRect().left) / card.offsetWidth) - .5) * 9 : nx * 3;
    tiltX = lerp(tiltX, tX, .08); tiltY = lerp(tiltY, tY, .08);
    card.style.setProperty('--rx', (lerp(10, 2, lift) + tiltX) + 'deg');
    card.style.setProperty('--ry', tiltY + 'deg');
    card.style.setProperty('--ty', (lerp(24, -10, lift)) + 'px');
    pX = lerp(pX, nx, .06); pY = lerp(pY, ny, .06);
    chips.forEach(c => {
      const d = +c.dataset.depth || 20;
      c.style.setProperty('--px', (pX * d).toFixed(2) + 'px');
      c.style.setProperty('--py', (pY * d * .7 + lift * d * -.9).toFixed(2) + 'px');
    });

    // backtest : progression 0 → 1 sur la hauteur épinglée
    const br = bt.getBoundingClientRect();
    const p = clamp(-br.top / (br.height - vh));
    bt.style.setProperty('--p', p.toFixed(3));
    const shown = Math.floor(clamp((p - .06) / .62) * chars.length);
    for (let i = 0; i < chars.length; i++) chars[i].classList.toggle('on', i < shown);
    btGlyph.classList.toggle('in', br.top < vh * .6);
    btRule.style.transform = `scaleX(${clamp((p - .66) / .14)})`;
    btSign.classList.toggle('in', p > .78);
    if (p > .84 && !figDone) { figDone = true; count(btFig, 1500); }
    if (p < .6 && figDone) { figDone = false; btFig.textContent = '0'; }

    // footer : révélations déclenchées par la position (filet de sécurité de l'observer)
    $$('.footer [data-in], #footWord').forEach(el => { if (!el.classList.contains('in') && el.getBoundingClientRect().top < vh * .85) el.classList.add('in'); });

    requestAnimationFrame(loop);
  }
  if (!reduced) requestAnimationFrame(loop);
})();
