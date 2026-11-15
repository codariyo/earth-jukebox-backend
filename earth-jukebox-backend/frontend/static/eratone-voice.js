/* Eratone — seslendirme (Kadın / Erkek). Alt paneldeki "Seslendirme Modu" düğmelerini çalıştırır.

   Ne söyler: seçili haritanın adı, bölge, tarih ve bölgenin GERÇEK değerleri (ortalama, en düşük,
   en yüksek, nerede yüksek) — metni backend üretir: GET /api/narration/{tema}.
   Hangi ses: doğal (neural) Türkçe sesler — Kadın: Emel, Erkek: Ahmet → GET /api/speech (MP3, akış).
   İnternet ya da servis yoksa Windows'un yerel Türkçe sesine (Microsoft Tolga) düşer.

   Her anlatımın sonunda çalan (seçili) enstrümanlar okunur; tarih aralığı seçiliyse aralık okunur
   ("1 Haziran 2024 ile 1 Ağustos 2024 arası, 12 kare").

   Ne zaman konuşur:
     - açılış ekranında: hoş geldin ("Devam etmek için herhangi bir yere tıklayın"); tıklayınca kesilir
     - uygulamaya geçince: tıklama BEKLEMEDEN o anki harita (pencere otomatik çalmaya izin verir:
       eratone_app.py WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS --autoplay-policy=no-user-gesture-required)
     - Kadın/Erkek düğmesine basınca (kısa giriş + o anki harita)
     - tema, bölge ya da (üstteki Görüntüle ile) tarih değişince; tarih aralığı uygulanınca bir kez
     - takvimde tarih seçilince (Görüntüle'ye basmadan önce) ve aralık alanları değişince
     - ekolayzer: panel açılınca bant özeti; bant / enstrüman ses düzeyi bırakılınca yeni değer
     - enstrüman açılıp kapanınca: yalnız güncel enstrüman listesi (600 ms bekleyip son durum)
     - aralık karelerinde KONUŞMAZ (her karede konuşmak müziği bastırırdı); ?ej=1 test kancasında otomatik
       konuşmalar (açılış/varış) kapalı
   Seçili düğmeye yeniden basmak seslendirmeyi kapatır (eratone.html 'eratone:voice' olayı).

   Uyum: konuşma sırasında müzik yumuşakça kısılır (/api/audio/duck), bitince geri açılır; konuşma
   metni ekranda altyazı olarak görünür; yeni anlatım eskisini keser (üst üste binmez). */
(function () {
  'use strict';

  const pills = Array.from(document.querySelectorAll('.voice-pill[data-voice]'));
  const stage = document.querySelector('.center-stage');
  if (!pills.length || !stage) return;

  const DEBOUNCE_MS = 900;             // art arda seçimlerde yalnız sonuncusu anlatılsın
  const LABEL = { tr_female: 'Kadın sesi (Emel)', tr_male: 'Erkek sesi (Ahmet)' };

  let voice = (pills.find((p) => p.classList.contains('active')) || {}).dataset?.voice || null;
  let lastView = null, lastKey = '', timer = 0, token = 0, ducked = false, firstView = true;

  // ---------------- altyazı ----------------
  const caption = document.createElement('div');
  caption.className = 'ej-voice-caption';
  caption.setAttribute('role', 'status');
  caption.setAttribute('aria-live', 'polite');
  caption.hidden = true;
  stage.appendChild(caption);

  function showCaption(text, note) {
    caption.innerHTML = '';
    const who = document.createElement('b');
    who.textContent = (LABEL[voice] || 'Seslendirme') + (note ? ` · ${note}` : '');
    const body = document.createElement('span');
    body.textContent = text;
    caption.append(who, body);
    caption.hidden = false;
  }
  function speaking(on) {
    pills.forEach((p) => p.classList.toggle('is-speaking', on && p.dataset.voice === voice));
    if (!on) caption.hidden = true;
    duck(on);
  }

  // ---------------- müzik kısma ----------------
  function duck(on) {
    if (on === ducked) return;
    ducked = on;
    fetch('/api/audio/duck', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ on }) }).catch(() => {});
  }

  // ---------------- çalma ----------------
  const audio = new Audio();
  audio.preload = 'auto';
  audio.volume = 1.0;
  let fallbackText = '';
  audio.addEventListener('playing', () => speaking(true));
  audio.addEventListener('ended', () => speaking(false));
  audio.addEventListener('pause', () => { if (!audio.ended) speaking(false); });
  audio.addEventListener('error', () => {
    // doğal ses alınamadı (internet / servis): yerel Windows sesine düş
    if (fallbackText && audio.getAttribute('src')) speakLocal(fallbackText, ++token);
  });

  function stopAll() {
    token++;
    clearTimeout(timer);
    try { audio.pause(); } catch (e) { /* yok */ }
    audio.removeAttribute('src');
    fallbackText = '';
    if (window.speechSynthesis) speechSynthesis.cancel();
    speaking(false);
  }

  function speakLocal(text, t) {
    if (!window.speechSynthesis) { speaking(false); return; }
    const pick = () => speechSynthesis.getVoices().find((v) => /^tr/i.test(v.lang));
    const go = () => {
      if (t !== token) return;
      const v = pick();
      if (!v) { showCaption(text, 'bu bilgisayarda Türkçe ses yok'); setTimeout(() => { if (t === token) speaking(false); }, 6000); return; }
      const u = new SpeechSynthesisUtterance(text);
      u.voice = v; u.lang = v.lang; u.rate = 0.95; u.volume = 1;
      u.onstart = () => { if (t === token) { speaking(true); showCaption(text, voice === 'tr_female' ? 'internet yok: yerel erkek sesi' : 'internet yok: yerel ses'); } };
      u.onend = u.onerror = () => { if (t === token) speaking(false); };
      speechSynthesis.cancel();
      speechSynthesis.speak(u);
    };
    if (pick()) go(); else { speechSynthesis.onvoiceschanged = go; setTimeout(go, 800); }
  }

  /** Arayüzde seçili (açık) enstrümanlar, arayüzdeki sırayla: ['acoustic_guitar', 'piano', …] */
  function activeInstruments() {
    const inst = (window.eratoneAudio && window.eratoneAudio.instruments) || {};
    return Object.keys(inst).filter((k) => inst[k] && inst[k].active);
  }

  /** Hazır metni seçili sesle söyler (altyazı + müzik kısma + yerel yedek). */
  function say(text, t) {
    if (t !== token || !text) return;
    showCaption(text);
    fallbackText = text;
    audio.src = `/api/speech?${new URLSearchParams({ voice, text })}`;
    audio.play().catch(() => { if (t === token) speakLocal(text, t); });
  }

  async function narrate(intro) {
    if (!voice || !lastView) return;
    stopAll();
    const t = token;
    const st = (window.eratoneData && window.eratoneData.state) || {};
    const q = new URLSearchParams({ date: lastView.date, region: lastView.region || 'dunya',
      instruments: activeInstruments().join(',') });          // anlatımın sonunda çalan enstrümanlar
    if (intro) q.set('intro', 'true');
    if (st.range && st.range.isos && st.range.isos.length > 1) {
      q.set('range_start', st.range.isos[0]);
      q.set('range_end', st.range.isos[st.range.isos.length - 1]);
      q.set('frames', String(st.range.isos.length));
    }
    let text = '';
    try {
      const r = await fetch(`/api/narration/${encodeURIComponent(lastView.theme)}?${q}`);
      const j = await r.json();
      text = j && j.text ? j.text : '';
      if (!text && j && j.error) text = 'Bu harita için anlatım hazırlanamadı.';
    } catch (e) {
      text = 'Bu harita için anlatım hazırlanamadı.';
    }
    say(text, t);
  }

  /** Enstrüman açılıp kapanınca güncel listeyi kısaca söyler ("Çalan enstrümanlar: piyano ve keman."). */
  async function announceInstruments() {
    if (!voice) return;
    stopAll();
    const t = token;
    const q = new URLSearchParams({ instruments_only: 'true', instruments: activeInstruments().join(',') });
    try {
      const j = await (await fetch(`/api/narration/${encodeURIComponent((lastView && lastView.theme) || 'sicaklik')}?${q}`)).json();
      say(j && j.text, t);
    } catch (e) { /* anlatım olmadan devam */ }
  }

  // ---------------- tetikleyiciler ----------------
  function viewKey(v) {
    const st = (window.eratoneData && window.eratoneData.state) || {};
    const r = st.range && st.range.isos && st.range.isos.length > 1
      ? `aralik:${st.range.isos[0]}:${st.range.isos[st.range.isos.length - 1]}:${st.range.isos.length}` : v.date;
    return [v.theme, v.region, r].join('|');
  }
  const TEST = /[?&]ej=1(&|$)/.test(location.search);      // test kancası: otomatik konuşmalar kapalı
  const HAS_INTRO = !!document.getElementById('intro');      // açılış animasyonu var mı (?intro=0 ile yok)
  let appNarrationPending = false;

  /** Uygulamaya geçildiğinde (ya da açılış yoksa ilk görünümde) tıklama beklemeden haritayı anlat. */
  function narrateOnArrival() {
    if (!voice || TEST) return;
    if (!lastView) { appNarrationPending = true; return; }
    appNarrationPending = false;
    lastKey = viewKey(lastView);
    clearTimeout(timer);
    timer = setTimeout(() => narrate(true), 700);
  }

  window.addEventListener('eratone:view', (e) => {
    if (!e.detail) return;
    lastView = e.detail;
    const key = viewKey(lastView);
    if (firstView) {
      firstView = false;
      lastKey = key;
      if (appNarrationPending || (!HAS_INTRO && !TEST)) narrateOnArrival();
      return;
    }
    if (key === lastKey) return;                                    // zoom / kaydırma / aralık karesi
    lastKey = key;
    if (!voice) return;
    clearTimeout(timer);
    timer = setTimeout(() => narrate(false), DEBOUNCE_MS);
  });

  // Enstrüman düğmeleri (eratone.html 'eratone:audio' {type:'instrument'}): art arda tıklamada yalnız son durum
  let instTimer = 0;
  document.addEventListener('eratone:audio', (e) => {
    if (!voice || !e.detail || e.detail.type !== 'instrument') return;
    clearTimeout(instTimer);
    clearTimeout(timer);
    instTimer = setTimeout(announceInstruments, 600);
  });

  document.addEventListener('eratone:voice', (e) => {
    voice = (e.detail && e.detail.voice) || null;
    if (!voice) { stopAll(); return; }
    narrate(true);
  });

  // ---------------- kısa arayüz anlatımları (2026-11-15) ----------------
  const MONTHS = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];
  const sayDate = (iso) => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || ''); return m ? `${+m[3]} ${MONTHS[+m[2] - 1]} ${m[1]}` : iso; };
  const sayNum = (v) => String(v).replace('.', ',');
  const sayDb = (v) => (v === 0 ? 'sıfır' : `${v > 0 ? 'artı' : 'eksi'} ${sayNum(Math.abs(v))}`) + ' desibel';
  function sayText(text) {
    if (!voice || !text) return;
    stopAll();
    say(text, token);
  }
  /** Art arda değişimlerde (silindir çevirme, kaydırıcı sürükleme) yalnız son durum söylensin. */
  const later = (() => { let id = 0; return (fn, ms) => { clearTimeout(id); id = setTimeout(fn, ms); }; })();

  // Açılış ekranı: hoş geldin; ekrana tıklayınca (fırlatma) kesilir; uygulamaya geçince harita anlatılır
  if (HAS_INTRO && !TEST) {
    setTimeout(() => {
      if (document.body.classList.contains('intro-active') && document.body.dataset.state === 'idle') {
        sayText('Eratone\'a hoş geldiniz. NASA uydu verisiyle değişen dünyayı dinlemeye hazırız. ' +
                'Devam etmek için ekranda herhangi bir yere tıklayın.');
      }
    }, 1500);
  }
  window.addEventListener('eratone:intro-launch', () => stopAll());
  window.addEventListener('eratone:app-ready', narrateOnArrival);

  // Takvim: tarih seçilince (Görüntüle'ye basmadan önce) söyle
  window.addEventListener('eratone:date-picked', (e) => {
    if (!voice || !e.detail) return;
    later(() => sayText(`Seçilen tarih: ${sayDate(e.detail.date)}. Haritayı bu tarihe getirmek için Görüntüle'ye basın.`), 1100);
  });

  // Tarih aralığı paneli: başlangıç / bitiş / kare sayısı değişince seçilen aralığı söyle
  function sayRangeSelection() {
    const sum = (document.getElementById('range-summary') || {}).textContent || '';
    const m = /^(.+?)\s*→\s*(.+?)\s*·\s*(\d+) gün\s*·\s*(\d+) kare/.exec(sum.trim());
    if (!m) return;
    const on = document.getElementById('range-mode')?.classList.contains('on');
    sayText(`Seçilen tarih aralığı: ${m[1]} ile ${m[2]} arası, ${m[3]} gün, ${m[4]} kare. ` +
      (on ? 'Görüntüle\'ye basınca kareler oynar.' : 'Görmek için aralık modunu açıp Görüntüle\'ye basın.'));
  }
  ['range-start', 'range-end', 'range-frames'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('change', () => { if (voice) later(sayRangeSelection, 900); });
  });
  document.querySelectorAll('#range-presets button, #frames-minus, #frames-plus').forEach((b) =>
    b.addEventListener('click', () => { if (voice) later(sayRangeSelection, 900); }));

  // Ekolayzer paneli: açılınca bantların özeti; bant ya da enstrüman ses düzeyi değişince yeni değer
  const BAND = { 'val-60hz': 'Bas', 'val-250hz': 'Düşük mid', 'val-1khz': 'Orta frekans', 'val-4khz': 'Yüksek mid', 'val-12khz': 'Tiz' };
  const INST = { acoustic_guitar: 'Akustik gitar', electric_guitar: 'Elektro gitar', piano: 'Piyano', flute: 'Yan flüt', violin: 'Keman' };
  const eqSliders = Array.from(document.querySelectorAll('.eq-slider'));
  const eqBtn = document.getElementById('btn-toggle-eq');
  if (eqBtn) eqBtn.addEventListener('click', () => setTimeout(() => {
    const panel = document.getElementById('sidebar-equalizer');
    if (!voice || !panel || !panel.classList.contains('open')) return;
    const bands = eqSliders.map((s) => `${(BAND[s.dataset.target] || '').toLowerCase()} ${sayDb(+s.value).replace(' desibel', '')}`);
    sayText(`Ekolayzer açıldı. ${bands.join(', ')} desibel. Enstrüman ses düzeylerini de bu panelden ayarlayabilirsiniz.`);
  }, 80));
  eqSliders.forEach((s) => s.addEventListener('change', () => {
    if (voice && BAND[s.dataset.target]) later(() => sayText(`${BAND[s.dataset.target]}, ${sayDb(+s.value)}.`), 500);
  }));
  document.querySelectorAll('.mix-slider').forEach((s) => s.addEventListener('change', () => {
    if (voice && INST[s.dataset.inst]) later(() => sayText(`${INST[s.dataset.inst]} ses düzeyi yüzde ${s.value}.`), 500);
  }));

  window.eratoneVoice = { narrate, stop: stopAll, get voice() { return voice; } };   // hata ayıklama / test
})();
