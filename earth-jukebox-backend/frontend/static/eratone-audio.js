/* Eratone — ses köprüsü (Faz 5). Arayüzün müzik kontrollerini world-sound motoruna bağlar.

   Motor backend'de çalışır (app/audio.py → world-sound/worldsound) ve sesi BU bilgisayarın
   hoparlörüne verir. Harita verisi motorun kendi NASA istemcisinden DEĞİL, uygulamanın
   backend'inden gelir (aynı katman, aynı tarih, aynı önbellek).

   Bağlantılar:
     eratone.html (tasarım)                        →  /api/audio/*
       'eratone:audio' {type:'play'}   Oynat/Duraklat →  play {playing}
       'eratone:audio' {type:'loop'}   Döngü          →  loop {loop}
       'eratone:audio' {type:'instrument'} pill      →  instrument {key, enabled}
       'eratone:audio' {type:'volume'} mixer slider  →  instrument {key, volume}
       .eq-slider 'input' (olay yaymıyor, doğrudan)   →  eq {band, db}
       #speed-slider (oynat altındaki hız çubuğu)    →  speed {factor 0.25…2}
     eratone-data.js 'eratone:view' {theme,date,source,box}  →  source + view
   Geri bildirim: /api/audio/state (çalarken ~8/sn) → çalan notalar şeridi, 2D'de tarama çizgisi,
   ekolayzer panelindeki 8 çubuk (gerçek spektrum).

   İlk "Çal"a kadar backend'e hiçbir şey gönderilmez (ses kartı / NASA isteği boşuna açılmasın);
   ilk "Çal"da arayüzün o anki enstrüman / ses düzeyi / EQ / döngü durumu toplu gönderilir.
   Seslendirme (Kadın/Erkek) ayrı dosyada: eratone-voice.js (konuşurken müziği /api/audio/duck ile kısar).
*/
(function () {
  'use strict';

  const INSTRUMENTS = ['acoustic_guitar', 'electric_guitar', 'piano', 'flute', 'violin'];
  // eratone.html EQ kaydırıcısı (data-target) → worldsound bandı (sıra aynı; frekanslar motorun: 100/300/1k/3k/8k)
  const EQ_MAP = { 'val-60hz': 'bass', 'val-250hz': 'low_mid', 'val-1khz': 'mid', 'val-4khz': 'high_mid', 'val-12khz': 'treble' };
  const POLL_MS = 120;

  const audioState = window.eratoneAudio;               // eratone.html'in ses durumu
  const stage = document.querySelector('.center-stage');
  const el2d = document.getElementById('globe-2d');
  const playBtn = document.getElementById('btn-main-play');
  if (!audioState || !stage || !el2d) { console.warn('[eratone-audio] arayüz öğeleri bulunamadı'); return; }

  // ---------------- görsel öğeler ----------------
  const pill = document.createElement('div');           // çalan notalar
  pill.className = 'ej-notes';
  pill.hidden = true;
  stage.appendChild(pill);
  const scan = document.createElement('div');           // 2D tarama çizgisi
  scan.className = 'ej-scanline';
  scan.hidden = true;
  el2d.appendChild(scan);
  const viz = document.querySelector('.eq-visualizer');
  const bars = viz ? Array.from(viz.querySelectorAll('.eq-bar')) : [];

  // ---------------- backend ----------------
  let lastError = '';
  async function post(path, body) {
    try {
      const r = await fetch('/api/audio/' + path, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      const isJson = (r.headers.get('content-type') || '').includes('json');
      const j = isJson ? await r.json() : { ok: false, error: `HTTP ${r.status}` };
      if (j && j.ok === false && !j.stale && j.error) showError(j.error);
      return j;
    } catch (e) {
      showError(String(e));
      return { ok: false };
    }
  }
  function showError(msg) {
    lastError = msg;
    pill.hidden = false;
    pill.classList.add('is-error');
    pill.textContent = `Ses: ${msg}`;
  }

  // ---------------- görünüm → kaynak + görünür kutu ----------------
  let armed = false;
  let lastView = null, sentSource = '', sentBox = '', sentRegion = null, restartUntil = 0;
  function sendView(force) {
    if (!armed || !lastView) return;
    const v = lastView;
    const srcKey = [v.theme, v.date, v.source.join(',')].join('|');
    if (force || srcKey !== sentSource) {
      sentSource = srcKey;
      post('source', { theme: v.theme, date: v.date, bbox: v.source });
    }
    // Bölge değişti → tarama yeni bölgenin başından (3D'de kaynak dünya kalıyor, yalnız görünüm değişiyordu).
    // Küre ~1,2 sn dönerek bölgeye gider; bu sürede gelen her görünümde yeniden başlat ki tarama SON
    // (kürenin durduğu) görünümün başından başlasın.
    if (sentRegion !== null && v.region !== sentRegion) restartUntil = performance.now() + 1500;
    sentRegion = v.region;
    const restart = performance.now() < restartUntil;
    const boxKey = v.box.map((x) => x.toFixed(3)).join(',');
    if (force || restart || boxKey !== sentBox) {
      sentBox = boxKey;
      const [west, south, east, north] = v.box;
      post('view', { west, south, east, north, restart });
    }
  }
  window.addEventListener('eratone:view', (e) => { lastView = e.detail; sendView(false); });

  // ---------------- müzik hızı (oynat düğmesinin altındaki çubuk) ----------------
  // 0.25x … 2x, 0.25 adım; uygulama HER AÇILIŞTA 1x (kaydedilmez). Tarama temposunu değiştirir, perdeyi değil.
  // Çift tıklama 1x'e döndürür. Çalmadan önceki ayar ilk "Çal"da arm() ile gider.
  const speedSlider = document.getElementById('speed-slider');
  const speedBox = document.getElementById('speed-control');
  const speedBubble = document.getElementById('speed-bubble');
  let speed = 1, speedSent = 1;
  const fmtSpeed = (v) => `${v}x`;                      // 0.25x, 0.5x, 1x, 1.5x, 2x
  function paintSpeed() {
    const v = +speedSlider.value;
    speed = v;
    const pos = (v - 0.25) / 1.75;
    speedSlider.style.setProperty('--fill', (pos * 100).toFixed(3) + '%');
    if (speedBox) { speedBox.style.setProperty('--pos', pos.toFixed(4)); speedBox.classList.toggle('changed', v !== 1); }
    if (speedBubble) speedBubble.textContent = fmtSpeed(v);
    speedSlider.setAttribute('aria-valuetext', fmtSpeed(v));
  }
  if (speedSlider) {
    speedSlider.value = '1';
    paintSpeed();
    let last = 0, trail = 0;
    const send = () => {
      if (!armed || speed === speedSent) return;
      speedSent = speed;
      last = performance.now();
      post('speed', { factor: speed });
    };
    speedSlider.addEventListener('input', () => {
      paintSpeed();
      clearTimeout(trail);
      if (performance.now() - last >= 60) send(); else trail = setTimeout(send, 60);
    });
    speedSlider.addEventListener('change', () => { clearTimeout(trail); send(); });
    if (speedBox) {
      speedBox.addEventListener('dblclick', () => { speedSlider.value = '1'; paintSpeed(); clearTimeout(trail); send(); });
      speedSlider.addEventListener('pointerdown', () => speedBox.classList.add('dragging'));
      window.addEventListener('pointerup', () => speedBox.classList.remove('dragging'));
    }
  }

  /** İlk "Çal": arayüzün o anki ses ayarlarını motora toplu gönder. */
  async function arm() {
    if (armed) return;
    armed = true;
    const jobs = INSTRUMENTS.map((k) => {
      const i = audioState.instruments[k];
      return i ? post('instrument', { key: k, enabled: !!i.active, volume: i.volume }) : null;
    });
    document.querySelectorAll('.eq-slider').forEach((s) => {
      const band = EQ_MAP[s.dataset.target];
      if (band) jobs.push(post('eq', { band, db: +s.value }));
    });
    jobs.push(post('loop', { loop: !!audioState.loop }));
    speedSent = speed;
    jobs.push(post('speed', { factor: speed }));
    await Promise.all(jobs);
    sendView(true);
  }

  // ---------------- tasarımın ses olayları ----------------
  document.addEventListener('eratone:audio', async (e) => {
    const d = e.detail || {};
    const st = d.state || audioState;
    if (d.type === 'play') {
      if (st.playing) {
        lastError = '';
        pill.classList.remove('is-error');
        await arm();
        await post('play', { playing: true });
        startPolling();
      } else {
        post('play', { playing: false });
      }
      return;
    }
    if (!armed) return;                                 // çalmadan önceki değişiklikler arm() ile toplu gider
    if (d.type === 'loop') post('loop', { loop: !!st.loop });
    else if (d.type === 'instrument') post('instrument', { key: d.instrument, enabled: !!d.on });
    else if (d.type === 'volume' && st.instruments[d.instrument]) {
      post('instrument', { key: d.instrument, volume: st.instruments[d.instrument].volume });
    }
  });

  // EQ kaydırıcıları: eratone.html olay yaymıyor → 'input'u doğrudan dinle.
  // Sürüklerken DE duyulsun: en çok 40 ms'de bir gönder (kısma/throttle) + bırakınca son değer kesin gider.
  // (Eskiden 80 ms'lik bekletme vardı: sürükleme durana kadar hiçbir şey gitmiyordu.)
  // Motor kazancı yumuşak geçişle uygular (worldsound/equalizer.py), hızlı gönderim cızırtı yapmaz.
  document.querySelectorAll('.eq-slider').forEach((s) => {
    let last = 0, trail = 0, sent = null;
    const send = () => {
      const db = +s.value;
      if (db === sent) return;
      sent = db;
      last = performance.now();
      post('eq', { band: EQ_MAP[s.dataset.target], db });
    };
    s.addEventListener('input', () => {
      if (!armed) return;
      clearTimeout(trail);
      if (performance.now() - last >= 40) send();
      else trail = setTimeout(send, 40);
    });
    s.addEventListener('change', () => { if (armed) { clearTimeout(trail); send(); } });
  });

  // ---------------- durum: notalar, tarama çizgisi, spektrum ----------------
  let pollTimer = 0, sawPlaying = false;
  function startPolling() { if (!pollTimer) pollTimer = setTimeout(tick, 0); }
  async function tick() {
    pollTimer = 0;
    let st = null;
    try { st = await (await fetch('/api/audio/state')).json(); } catch (e) { st = null; }
    if (st) show(st);
    if (st && st.playing) sawPlaying = true;
    // Döngü kapalıyken tarama sonunda motor kendiliğinden durur → arayüzün Oynat düğmesini de geri al
    if (st && sawPlaying && !st.playing && audioState.playing && playBtn) { sawPlaying = false; playBtn.click(); }
    if (audioState.playing) pollTimer = setTimeout(tick, POLL_MS);
    else { sawPlaying = false; idle(); }
  }

  function show(st) {
    if (st.error && !st.audio_out) { showError(st.error); }
    else if (!lastError) {
      pill.hidden = false;
      pill.classList.remove('is-error');
      pill.textContent = !st.ready ? '♪ harita hazırlanıyor…'
        : st.notes && st.notes.length ? '♪ ' + st.notes.join(' · ')
        : '♪ — sessiz bölge (siyah / renksiz / ölçüm yok)';
    }
    const in2d = el2d.offsetParent !== null;
    scan.hidden = !(st.ready && st.playing && in2d);
    if (!scan.hidden) scan.style.left = (st.position * 100).toFixed(2) + '%';
    if (viz && bars.length && Array.isArray(st.spectrum) && st.spectrum.length) {
      viz.classList.add('ej-live');
      const n = st.spectrum.length, per = n / bars.length;
      bars.forEach((b, i) => {
        let m = 0;
        for (let k = Math.floor(i * per); k < Math.floor((i + 1) * per); k++) m = Math.max(m, st.spectrum[k] || 0);
        b.style.height = (6 + m * 94).toFixed(1) + '%';
      });
    }
  }
  function idle() {
    if (!lastError) pill.hidden = true;
    scan.hidden = true;
    if (viz) viz.classList.remove('ej-live');
    bars.forEach((b) => { b.style.height = ''; });
  }

  window.eratoneSound = { post, state: () => fetch('/api/audio/state').then((r) => r.json()) };   // hata ayıklama
})();
