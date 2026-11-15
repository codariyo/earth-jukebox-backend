/* Eratone — veri katmanı (Faz 2 + Faz 3). NASA görüntülerini yerel API'den çekip arayüze yerleştirir.

   Ne yapar:
     • Soldaki 6 harita kartı  → her birine kendi temasının önizlemesi (/api/texture, küçük).
       Kart seçilince o tema 3D küreye ve 2D haritaya gelir.
     • 3D küre                 → globe.gl (gerçek WebGL küre). Tuval TÜM orta sahneyi kaplar: yakınlaşınca
       gezegenin kavisi/ufku uzay zemininde görünür (Faz 3; önceden küçük kare tuvalde düz görünüyordu).
       Dünya dokusu önce 2048 (hızlı), sonra 4096 (net). Yakınlaşınca (irtifa < PATCH_MAX_ALT) bakılan
       bölgenin ekran çözünürlüğünde "detay yaması" çekilip küreye döşenir (globe.gl tilesData).
       Bölge seçilince küre o bölgeye döner. WebGL yoksa eski CSS küreye doku olarak uygulanır.
     • 2D harita               → seçili bölgenin görüntüsü; kutu görüntünün en/boy oranında, orta sahneye
       sığacak boyda; görüntü genişliği kutunun gerçek piksel sayısına göre (1024/2048/4096).
     • Tarih                   → açılışta DÜN (bugünün verisi eksik olur; bugün seçilebilir). Silindirden tarih seçip üstteki "Görüntüle" ile uygulanır.
       Faz 3: seçilebilir tarihler seçili temanın gerçek veri aralığıyla sınırlı (/api/themes first/last →
       window.eratoneSetDateLimits, eratone.html). Tema değişince uygulanmış tarih aralık dışındaysa içeri çekilir.
     • Tarih aralığı           → panelde başlangıç/bitiş/kare sayısı + "Görüntüle". Kare tarihleri
       eratone.html'deki rebuildFrames() hesaplar (gün farkı / (kare−1); ilk kare = başlangıç,
       son kare = bitiş). Bütün karelerin görüntüsü arka planda (6 paralel, oynatma sırasıyla) önbelleğe alınır.
       Aralık uygulanınca kareler KENDİLİĞİNDEN oynar (sahnede ▶/⏸ + hız düğmesi; sonraki kare gelmeden geçilmez).

   Arayüzle bağı (eratone.html'deki tasarım koduna bağımlılık bilerek az tutuldu):
     dinlenen olaylar : 'eratone:date-applied' {date}, 'eratone:range-applied' {frames:[iso]},
                        'eratone:frame' {index, date}  (showFrame içine eklendi)
     çağrılan         : window.eratoneSetDateLimits(minIso, maxIso)  (Faz 3, eratone.html)
     DOM              : .map-card[data-theme], .map-preview-slot, .region-item[data-region],
                        #btn-view-3d, #btn-view-2d, #globe-3d, #globe-2d, .center-stage, .globe-stage
   MÜZİK: Bu dosya sese HİÇ dokunmaz (bkz. CONTEXT.md bölüm 5b).
   Bölge kutuları app/config.py REGIONS ile AYNI tutulmalı. */
(function () {
  'use strict';

  // ---------------- sabitler ----------------
  const REGIONS = {               // arayüz etiketi -> [slug, [minLon, minLat, maxLon, maxLat]]
    'Dünya':         ['dunya',         [-180, -90, 180, 90]],
    'Türkiye':       ['turkiye',       [25, 35, 45, 43]],
    'Avrupa':        ['avrupa',        [-25, 34, 45, 72]],
    'Akdeniz':       ['akdeniz',       [-6, 30, 37, 46]],
    'Kuzey Amerika': ['kuzey_amerika', [-170, 10, -50, 75]],
    'Güney Amerika': ['guney_amerika', [-90, -60, -30, 15]],
    'Afrika':        ['afrika',        [-20, -37, 55, 38]],
    'Asya':          ['asya',          [40, -10, 150, 60]],
    'Avustralya':    ['avustralya',    [110, -45, 160, -8]],
    'Amazon':        ['amazon',        [-75, -15, -45, 5]],
    'Kuzey Kutbu':   ['kuzey_kutbu',   [-180, 60, 180, 90]],
  };
  const MONTHS = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos',
                  'Eylül', 'Ekim', 'Kasım', 'Aralık'];
  const GLOBE_W_LO = 2048;       // küre dokusu: önce bu (hızlı, çoğu zaman önbellekte)
  const GLOBE_W_HI = 4096;       // sonra bu (net). Backend üst sınırı: config.TEXTURE_MAX_WIDTH
  const GLOBE_W_RANGE = 2048;    // aralık karelerinde (çok kare = çok istek)
  const THUMB_W = 480;           // kart önizlemesi
  // Aynı anda en fazla bu kadar /api isteği. 3 → 6 (aralık kareleri sıraya giriyordu; tarayıcının host başına
  // bağlantı sınırı da 6). Backend NASA'ya 8 ile sınırlı (config.MAX_PARALLEL_GIBS).
  const MAX_PARALLEL = 6;
  const RANGE_MAP_W = 2048;      // 2D aralık karelerinde üst sınır (4096 kare başına ~8 sn sürüyordu)
  const CACHE_MAX = 160;         // bellekte tutulan görüntü sayısı
  // İrtifa (küre yarıçapı cinsinden). Tuval tüm sahneyi kaplar; küre yüksekliğin ~%74'ü:
  // ölçüm: kesir ≈ 1.94·tan(asin(1/(1+irtifa))) (dikey görüş açısına göre) → %74 için ≈ 1.8
  const WORLD_ALT = 1.8;
  // Ufuk (kürenin kenarı) ekranda kalsın diye: kenarın açısal yarıçapı asin(1/(1+irtifa)) yatay yarım görüş
  // açısından (~44°, 16:9 sahnede) küçük olmalı. 0.45'te kenar tam ekran kenarında, 0.6'da rahatça içeride.
  const MIN_ALT = 0.45;          // elle en yakın zoom (daha yakında yüzey düz görünür — kullanıcı şikâyeti, Faz 3)
  const MAX_ALT = 4;             // en uzak zoom
  const REGION_MIN_ALT = 0.6;    // bölge seçilince inilen en yakın irtifa (Türkiye, Akdeniz…): kavis görünür
  const PATCH_MAX_ALT = 1.0;     // bunun altındaki irtifada detay yaması çekilir
  const PATCH_LAT_SPANS = [16, 20, 24, 28, 32, 40, 48, 64, 80];  // yama yüksekliği kovaları (derece) — önbellek tekrar kullansın

  // ---------------- DOM ----------------
  const $ = (s) => document.querySelector(s);
  const stage = $('.center-stage');
  const globeStage = $('.globe-stage');
  const el3d = $('#globe-3d');
  const el2d = $('#globe-2d');
  const btn3d = $('#btn-view-3d');
  const btn2d = $('#btn-view-2d');
  const cards = Array.from(document.querySelectorAll('.map-card[data-theme]'));
  if (!stage || !el3d || !el2d || !cards.length) { console.warn('[eratone-data] arayüz öğeleri bulunamadı'); return; }

  const chip = document.createElement('div');
  chip.className = 'ej-data-chip';
  chip.setAttribute('role', 'status');
  chip.setAttribute('aria-live', 'polite');
  stage.appendChild(chip);

  const mapImg = document.createElement('img');
  mapImg.className = 'ej-map';
  mapImg.alt = '';
  mapImg.draggable = false;

  // ---------------- durum ----------------
  const today = () => { const t = new Date(); return new Date(t.getFullYear(), t.getMonth(), t.getDate()); };
  const yesterday = () => { const t = today(); t.setDate(t.getDate() - 1); return t; };
  const S = {
    theme: (cards.find((c) => c.classList.contains('active')) || cards[0]).dataset.theme,
    region: 'Dünya',
    // uygulanan tek tarih. Açılışta DÜN (Faz 3b, kullanıcı kararı): bugünün uydu geçişleri henüz işlenmemiş
    // olur, gerçek renk neredeyse siyah görünüyordu. eratone.html initDate silindiri de düne kurar.
    date: yesterday(),
    range: null,               // { isos:[...], idx } — "Görüntüle" ile uygulanan aralık
    view: (btn2d && btn2d.classList.contains('active')) ? '2d' : '3d',
    titles: {},                // tema -> başlık (/api/themes)
    info: {},                  // tema -> { first, last, unit, step } (/api/themes)
  };
  // Aralık oynatıcısı (aşağıda "aralık oynatıcı"). Burada tanımlı: schedulePatch/scheduleDetail açılışta da okur.
  const P = { playing: false, speed: 1, timer: 0, waiting: null, self: false };

  // ---------------- yardımcılar ----------------
  const pad = (n) => String(n).padStart(2, '0');
  const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const parseIso = (s) => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || ''); return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null; };
  const fmt = (s) => { const d = typeof s === 'string' ? parseIso(s) : s; return d ? `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}` : String(s); };
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const dpr = () => Math.min(2, window.devicePixelRatio || 1);
  const regionSlug = () => (REGIONS[S.region] || REGIONS['Dünya'])[0];
  const regionBox = () => (REGIONS[S.region] || REGIONS['Dünya'])[1];
  const title = (t) => S.titles[t] || (cards.find((c) => c.dataset.theme === t)?.querySelector('.map-card-title')?.textContent || t);
  const activeIso = () => (S.range ? S.range.isos[S.range.idx] : iso(S.date));

  /** /api/texture URL'si. `where`: bölge slug'ı ('dunya' = tüm dünya) ya da [minLon,minLat,maxLon,maxLat]. */
  function texUrl(theme, dateIso, width, where) {
    const q = new URLSearchParams({ date: dateIso, width: String(width) });
    if (Array.isArray(where)) q.set('bbox', where.map((v) => +v.toFixed(3)).join(','));
    else if (where && where !== 'dunya') q.set('region', where);
    return `/api/texture/${theme}?${q}`;
  }
  const globeUrl = (theme, d, hi) => texUrl(theme, d, S.range ? GLOBE_W_RANGE : (hi ? GLOBE_W_HI : GLOBE_W_LO), 'dunya');
  /** Kutunun gerçek piksel genişliğine göre 1024 / 2048 / 4096. */
  const widthFor = (px) => (px > 2200 ? 4096 : px > 1100 ? 2048 : 1024);
  function mapUrl(theme, d) {
    const w = widthFor(box2d().w * dpr());
    // Dünya seçiliyken 2D, küreyle AYNI dokuyu kullanır (aynı genişlikteyse tek istek, ortak önbellek)
    if (regionSlug() === 'dunya') return texUrl(theme, d, S.range ? GLOBE_W_RANGE : Math.max(2048, w), 'dunya');
    return texUrl(theme, d, S.range ? Math.min(RANGE_MAP_W, w) : w, regionSlug());
  }
  const viewUrl = (theme, d) => (S.view === '3d' ? globeUrl(theme, d, !S.range) : mapUrl(theme, d));

  // ---------------- tarih sınırları (Faz 3) ----------------
  /** Seçili temanın seçilebilir [ilk, son] tarihi. Aylık veride son ayın sonuna kadar, 8 günlükte son dönemin
      sonuna kadar seçilebilir (backend o döneme oturur). Bugünden ileri olamaz. */
  function limitsFor(theme) {
    const inf = S.info[theme];
    if (!inf || !inf.first) return null;
    const first = parseIso(inf.first);
    let last = parseIso(inf.last) || today();
    if (inf.unit === 'M') last = new Date(last.getFullYear(), last.getMonth() + (inf.step || 1), 0);
    else if (inf.unit === 'Y') last = new Date(last.getFullYear() + (inf.step || 1), 0, 0);
    else if ((inf.step || 1) > 1) last = new Date(last.getFullYear(), last.getMonth(), last.getDate() + inf.step - 1);
    if (last > today()) last = today();
    return { min: first, max: last };
  }
  /** Silindiri temaya göre sınırla; uygulanmış tarih aralık dışındaysa içeri çek. Değiştiyse true. */
  function applyLimits() {
    const lim = limitsFor(S.theme);
    if (!lim || typeof window.eratoneSetDateLimits !== 'function') return false;
    window.eratoneSetDateLimits(iso(lim.min), iso(lim.max));
    if (S.range) return false;                        // aralık uygulanmışsa kareler olduğu gibi (backend en yakına oturur)
    const d = S.date < lim.min ? lim.min : S.date > lim.max ? lim.max : null;
    if (!d) return false;
    S.clampNote = `${fmt(S.date)} bu veride yok; veri aralığı ${fmt(lim.min)} – ${fmt(lim.max)}`;
    S.date = d;
    return true;
  }

  // ---------------- istek kuyruğu + görüntü önbelleği ----------------
  // Aynı URL ikinci kez istenmez; öncelikli istek (o an ekrandaki) kuyruğun başına geçer.
  const Q = { running: 0, items: [] };
  const cache = new Map();       // url -> { p, item, src }
  const shown = new Set();       // ekranda kullanılan blob URL'leri (önbellekten atılırken iptal edilmesin)

  function pump() {
    while (Q.running < MAX_PARALLEL && Q.items.length) {
      const it = Q.items.shift();
      Q.running++;
      it.run().then(it.resolve, it.reject).finally(() => { Q.running--; pump(); });
    }
  }

  async function fetchImage(url) {
    const r = await fetch(url);
    const blob = await r.blob();
    return { src: URL.createObjectURL(blob), used: r.headers.get('X-Date-Used'), ok: r.ok, status: r.status };
  }

  const isReady = (url) => { const e = cache.get(url); return !!(e && e.src && !e.item); };

  /** `cancelable`: yalnızca aralık ön-yüklemesi true verir; tema/aralık değişince cancelBackground() bunları
      kuyruktan atar. Kart önizlemeleri iptal EDİLMEZ (Faz 2 hatası: tema değişince kartlar "—" kalıyordu). */
  function getImage(url, high, cancelable = false) {
    let e = cache.get(url);
    if (e) {
      cache.delete(url); cache.set(url, e);              // LRU: en sona taşı
      if (high && e.item) {                              // hâlâ kuyruktaysa öne al
        const i = Q.items.indexOf(e.item);
        if (i > 0) { Q.items.splice(i, 1); Q.items.unshift(e.item); }
        e.item.cancelable = false;
      }
      if (e.item && !cancelable) e.item.cancelable = false;   // başka biri de bekliyor: iptal edilmesin
      return e.p;
    }
    e = {};
    e.p = new Promise((resolve, reject) => {
      e.item = { url, cancelable: !high && cancelable, run: () => fetchImage(url), resolve, reject };
      if (high) Q.items.unshift(e.item); else Q.items.push(e.item);
    });
    cache.set(url, e);
    e.p.then((res) => {
      e.item = null; e.src = res.src;
      if (!res.ok) cache.delete(url);                    // hata görüntüsünü saklama, sonra tekrar denensin
    }, () => { e.item = null; cache.delete(url); });
    pump();
    trim();
    return e.p;
  }

  function trim() {
    for (const [url, e] of cache) {
      if (cache.size <= CACHE_MAX) break;
      if (e.item) continue;                              // bekleyen isteği atma
      cache.delete(url);
      if (e.src && !shown.has(e.src)) URL.revokeObjectURL(e.src);
    }
  }

  /** Kuyrukta bekleyen arka plan (önceden yükleme) isteklerini iptal et — tema/aralık değişince. */
  function cancelBackground() {
    Q.items = Q.items.filter((it) => {
      if (!it.cancelable) return true;
      cache.delete(it.url);
      it.reject(new Error('iptal'));
      return false;
    });
  }

  function markShown(src, prev) {
    if (prev && prev !== src) shown.delete(prev);
    if (src) shown.add(src);
  }

  // ---------------- durum şeridi ----------------
  function setChip(html, kind) {
    chip.innerHTML = html;
    chip.classList.toggle('is-loading', kind === 'loading');
    chip.classList.toggle('is-error', kind === 'error');
    chip.hidden = !html;
  }
  let chipExtra = '';            // örn. "netleştiriliyor…"
  let lastRes = null, lastReq = null;
  function describe(res, reqIso) {
    const used = res.used && res.used !== 'zamansiz' ? res.used : null;
    let s = `<b>${esc(title(S.theme))}</b> · ${esc(S.region)} · `;
    if (S.range) s += `kare ${S.range.idx + 1}/${S.range.isos.length} · `;
    s += `veri: <b>${esc(used ? fmt(used) : fmt(reqIso))}</b>`;
    if (S.clampNote) s += ` <span class="ej-note">(${esc(S.clampNote)})</span>`;
    else if (used && used !== reqIso) s += ` <span class="ej-note">(${esc(fmt(reqIso))} için veri yok, en yakın tarih)</span>`;
    if (S.range && S.range.total) s += ` · önbellek ${S.range.done}/${S.range.total}`;
    if (chipExtra) s += ` · ${esc(chipExtra)}`;
    return s;
  }
  function refreshChip() { if (lastRes) setChip(describe(lastRes, lastReq)); }

  // ---------------- 3D küre ----------------
  let G = null;            // globe.gl örneği
  let flat = false;        // WebGL yoksa CSS yedeği
  let globeSrc = null;
  let maxAniso = 1;

  function initGlobe() {
    if (typeof window.Globe !== 'function') { useFlat('globe.gl yüklenemedi'); return; }
    try {
      G = new window.Globe(el3d, { animateIn: false })
        .backgroundColor('rgba(0,0,0,0)')
        .showAtmosphere(true).atmosphereColor('#38bdf8').atmosphereAltitude(0.14)
        .showGraticules(false)
        // detay yaması (Faz 3): karo merkezi lat/lng, genişlik/yükseklik derece; doku eşdikdörtgen
        .tileLat('lat').tileLng('lng').tileWidth('w').tileHeight('h')
        .tileAltitude(0.0012).tileMaterial('mat').tileCurvatureResolution(1)
        .tilesTransitionDuration(0)
        .onZoom(() => { schedulePatch(); emitView(); });
      const R = G.renderer();
      R.setPixelRatio(dpr());                            // yüksek DPI ekranda keskin çizim
      maxAniso = R.capabilities.getMaxAnisotropy ? R.capabilities.getMaxAnisotropy() : 1;
      const c = G.controls();
      c.autoRotate = true;
      c.autoRotateSpeed = 0.5;
      c.enableZoom = true;
      c.minDistance = 100 * (1 + MIN_ALT);               // globe.gl küre yarıçapı = 100 birim
      c.maxDistance = 100 * (1 + MAX_ALT);
      c.zoomSpeed = 0.8;
      G.pointOfView({ lat: 20, lng: 30, altitude: WORLD_ALT }, 0);
      el3d.classList.add('has-globe');
      el3d.title = 'Sürükle: döndür · Tekerlek: yakınlaş';
      // Kullanıcı tutunca otomatik dönüş dursun; Dünya görünümünde ve uzaktayken bırakınca devam etsin
      el3d.addEventListener('pointerdown', () => { c.autoRotate = false; });
      el3d.addEventListener('pointerup', () => {
        if (regionSlug() === 'dunya' && G.pointOfView().altitude >= PATCH_MAX_ALT) c.autoRotate = true;
      });
    } catch (err) {
      G = null;
      useFlat(err && err.message);
    }
  }
  function useFlat(reason) {
    flat = true;
    el3d.classList.add('has-flat');
    console.warn('[eratone-data] 3D küre yerine düz doku kullanılıyor:', reason);
  }
  /** globe.gl dokuyu kendi yükler; yüklenince anizotropik filtre ver (eğik bakışta keskinlik). */
  function tuneGlobeTexture(src, n = 0) {
    if (!G) return;
    const m = G.globeMaterial();
    if (m && m.map && m.map.image && m.map.image.src === src) {
      if (m.map.anisotropy !== maxAniso) { m.map.anisotropy = maxAniso; m.map.needsUpdate = true; }
      return;
    }
    if (n < 600 && src === globeSrc) requestAnimationFrame(() => tuneGlobeTexture(src, n + 1));
  }
  function applyGlobe(src) {
    markShown(src, globeSrc);
    globeSrc = src;
    if (G) { G.globeImageUrl(src); tuneGlobeTexture(src); }
    else if (flat) el3d.style.setProperty('--ej-tex', `url("${src}")`);
  }
  function aimGlobe(ms) {
    if (!G) return;
    const [x0, y0, x1, y1] = regionBox();
    const c = G.controls();
    if (regionSlug() === 'dunya') {
      c.autoRotate = true;
      G.pointOfView({ lat: 20, altitude: WORLD_ALT }, ms);
      return;
    }
    c.autoRotate = false;
    const span = Math.max(x1 - x0, (y1 - y0) * 1.6);
    G.pointOfView({ lat: (y0 + y1) / 2, lng: (x0 + x1) / 2, altitude: clamp(span / 100, REGION_MIN_ALT, WORLD_ALT) }, ms);
  }

  // ---------------- detay yaması (Faz 3) ----------------
  // Yakınlaşınca dünya dokusu (4096 px / 360° ≈ 11 px/derece) bulanık kalır. Bakılan alanın görüntüsü
  // ekranın piksel sayısına uygun genişlikte (2048/4096) ayrıca çekilip küreye karo olarak döşenir.
  let patch = { key: null, mat: null, tex: null };
  let patchTimer = 0, patchToken = 0;

  function schedulePatch() {
    clearTimeout(patchTimer);
    if (P.playing) return;                               // oynatırken kare başına yama isteği kareleri geciktirir
    patchTimer = setTimeout(updatePatch, 450);
  }
  function clearPatch() {
    patchToken++;
    if (!patch.key) return;
    if (G) G.tilesData([]);
    if (patch.mat) patch.mat.dispose();
    if (patch.tex) patch.tex.dispose();
    patch = { key: null, mat: null, tex: null };
  }
  /** Bakılan alanı kapsayan, önbellek için yuvarlanmış kutu:
      {box:[x0,y0,x1,y1], lat, lng, w, h, px} ya da null. px = ekranın derece başına pikseline denk görüntü genişliği. */
  function patchBox(pov) {
    const aspect = Math.max(1, stage.clientWidth / Math.max(1, stage.clientHeight));
    const cosLat = Math.max(0.2, Math.cos(pov.lat * Math.PI / 180));
    // Görünen dikey yay ≈ 2·irtifa·tan(~27.5°) radyan (dikey görüş açısı ölçümle ~55°) → derece
    const visLat = 2 * pov.altitude * 0.52 * 57.3;
    const visLon = visLat * aspect / cosLat;
    const h = PATCH_LAT_SPANS.find((s) => s >= visLat * 1.15) || PATCH_LAT_SPANS[PATCH_LAT_SPANS.length - 1];
    const w = Math.ceil((h * aspect / cosLat) / 8) * 8;
    if (w >= 300) return null;                           // neredeyse tüm boylamlar: dünya dokusu yeter
    const gy = h / 4, gx = w / 4;                        // merkez ızgaraya oturur → küçük dönüşte aynı yama
    let lat = Math.round(pov.lat / gy) * gy;
    let lng = Math.round(pov.lng / gx) * gx;
    lat = clamp(lat, -90 + h / 2, 90 - h / 2);
    lng = clamp(lng, -180 + w / 2, 180 - w / 2);         // tarih değiştirme çizgisini aşmasın (API sınırı)
    // Ekranda derece başına düşen piksel × yama genişliği (derece) → gereken görüntü genişliği
    const px = Math.min(GLOBE_W_HI, widthFor(stage.clientWidth * dpr() * w / visLon));
    return { box: [lng - w / 2, lat - h / 2, lng + w / 2, lat + h / 2], lat, lng, w, h, px };
  }
  async function updatePatch() {
    if (!G || flat || S.view !== '3d') { clearPatch(); return; }
    const pov = G.pointOfView();
    if (pov.altitude >= PATCH_MAX_ALT) { clearPatch(); return; }
    const pb = patchBox(pov);
    if (!pb) { clearPatch(); return; }
    const url = texUrl(S.theme, activeIso(), pb.px, pb.box);
    if (url === patch.key) return;
    const t = ++patchToken;
    chipExtra = 'yakın görüntü netleştiriliyor…'; refreshChip();
    let res;
    try { res = await getImage(url, true); } catch (e) { res = null; }
    if (t !== patchToken) return;
    chipExtra = ''; refreshChip();
    if (!res || !res.ok) return;
    const base = G.globeMaterial();
    if (!base || !base.map) return;                      // dünya dokusu henüz yüklenmedi
    const img = new Image();
    img.src = res.src;
    try { await img.decode(); } catch (e) { return; }
    if (t !== patchToken) return;
    const tex = new base.map.constructor(img);           // THREE.Texture (globe.gl paketinden; global THREE yok)
    if ('colorSpace' in base.map) tex.colorSpace = base.map.colorSpace;
    if ('encoding' in base.map) tex.encoding = base.map.encoding;
    tex.anisotropy = maxAniso;
    tex.needsUpdate = true;
    const mat = new base.constructor({ map: tex });      // kürenin malzemesiyle aynı tür → aynı ışık/gölge
    if ('shininess' in base) mat.shininess = base.shininess;
    const old = patch;
    patch = { key: url, mat, tex, src: res.src };
    markShown(res.src, old.src);
    G.tilesData([{ lat: pb.lat, lng: pb.lng, w: pb.w, h: pb.h, mat }]);
    if (old.mat) old.mat.dispose();
    if (old.tex) old.tex.dispose();
  }

  // ---------------- 2D yakınlaştırma (Faz 4) ----------------
  // Tekerlek: imlecin altındaki nokta sabit kalarak 1×–Z_MAX× zoom. Yakınken sürükle: kaydır (kenardan taşmaz).
  // Çift tık: 2× yaklaş / sığdır. Köşede + − ⤢ butonları (klavye/ekran okuyucu için).
  // Zoom tema/tarih/aralık karesi değişince KORUNUR (aynı yeri karşılaştırmak için); bölge değişince sıfırlanır.
  // Zoom durunca görünen alan /api/texture?bbox= ile kutunun piksel sayısında ayrıca çekilip üstüne konur
  // (ana görüntü en çok 4096 px; 4× zoomda bulanıklaşırdı). Bkz. CONTEXT.md Faz 4.
  const Z = { s: 1, ox: 0, oy: 0 };       // ölçek; öteleme kutu boyuna ORANLA (yeniden boyutlanmada korunur)
  const Z_MAX = 12;
  const DETAIL_MSG = 'yakın görüntü netleştiriliyor…';
  const detailImg = document.createElement('img');
  detailImg.className = 'ej-map-detail';
  detailImg.alt = '';
  detailImg.draggable = false;
  const zoomUi = document.createElement('div');
  zoomUi.className = 'ej-zoom';
  zoomUi.setAttribute('role', 'group');
  zoomUi.setAttribute('aria-label', '2D harita yakınlaştırma');
  zoomUi.innerHTML =
    '<button type="button" data-z="in" aria-label="Yakınlaştır" title="Yakınlaştır (fare tekerleği)">+</button>' +
    '<span class="ej-zoom-val" aria-live="polite">1×</span>' +
    '<button type="button" data-z="out" aria-label="Uzaklaştır" title="Uzaklaştır">−</button>' +
    '<button type="button" data-z="reset" aria-label="Haritayı sığdır" title="Sığdır (çift tık)">⤢</button>';
  const zoomVal = zoomUi.querySelector('.ej-zoom-val');

  function ensure2dUi() {
    if (!detailImg.isConnected) el2d.appendChild(detailImg);
    if (!zoomUi.isConnected) el2d.appendChild(zoomUi);
  }
  const box2dNow = () => ({ W: el2d.clientWidth || 1, H: el2d.clientHeight || 1 });
  function applyZ(animate) {
    Z.s = clamp(Z.s, 1, Z_MAX);
    Z.ox = clamp(Z.ox, 1 - Z.s, 0);                      // görüntü kutuyu hep doldursun (kenardan boşluk yok)
    Z.oy = clamp(Z.oy, 1 - Z.s, 0);
    const { W, H } = box2dNow();
    mapImg.style.transition = animate ? 'transform .25s ease' : 'none';
    mapImg.style.transform = `translate(${Z.ox * W}px, ${Z.oy * H}px) scale(${Z.s})`;
    zoomVal.textContent = `${Z.s < 10 ? Z.s.toFixed(1) : Math.round(Z.s)}×`;
    el2d.classList.toggle('is-zoomed', Z.s > 1.001);
    zoomUi.querySelector('[data-z="out"]').disabled = Z.s <= 1.001;
    zoomUi.querySelector('[data-z="reset"]').disabled = Z.s <= 1.001;
    zoomUi.querySelector('[data-z="in"]').disabled = Z.s >= Z_MAX - 0.001;
    hideDetail();
    scheduleDetail();
    emitView();                                          // Faz 5: müzik görünen pencereye geçsin
  }
  /** (mx,my) kutu içindeki piksel; o noktanın altındaki harita yeri sabit kalır. */
  function zoomAt(factor, mx, my, animate) {
    const { W, H } = box2dNow();
    const s2 = clamp(Z.s * factor, 1, Z_MAX);
    const u = mx / W, v = my / H;
    const px = (u - Z.ox) / Z.s, py = (v - Z.oy) / Z.s;  // imlecin altındaki noktanın görüntüdeki yeri (0–1)
    Z.ox = u - px * s2;
    Z.oy = v - py * s2;
    Z.s = s2;
    applyZ(animate);
  }
  function resetZoom(animate) { Z.s = 1; Z.ox = 0; Z.oy = 0; if (mapImg.isConnected) applyZ(animate); }

  el2d.addEventListener('wheel', (e) => {
    if (S.view !== '2d' || !mapImg.isConnected) return;
    e.preventDefault();
    const r = el2d.getBoundingClientRect();
    const dy = e.deltaY * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1);
    zoomAt(Math.exp(-dy * 0.0015), e.clientX - r.left, e.clientY - r.top, false);
  }, { passive: false });

  let drag = null;
  el2d.addEventListener('pointerdown', (e) => {
    if (Z.s <= 1.001 || e.button !== 0 || e.target.closest('.ej-zoom')) return;
    drag = { x: e.clientX, y: e.clientY, ox: Z.ox, oy: Z.oy };
    try { el2d.setPointerCapture(e.pointerId); } catch (err) { /* yok say */ }
    el2d.classList.add('is-panning');
  });
  el2d.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const { W, H } = box2dNow();
    Z.ox = drag.ox + (e.clientX - drag.x) / W;
    Z.oy = drag.oy + (e.clientY - drag.y) / H;
    applyZ(false);
  });
  const endDrag = (e) => {
    if (!drag) return;
    drag = null;
    try { el2d.releasePointerCapture(e.pointerId); } catch (err) { /* yok say */ }
    el2d.classList.remove('is-panning');
  };
  el2d.addEventListener('pointerup', endDrag);
  el2d.addEventListener('pointercancel', endDrag);
  el2d.addEventListener('dblclick', (e) => {
    if (e.target.closest('.ej-zoom') || !mapImg.isConnected) return;
    if (Z.s > 1.001) { resetZoom(true); return; }
    const r = el2d.getBoundingClientRect();
    zoomAt(2, e.clientX - r.left, e.clientY - r.top, true);
  });
  zoomUi.addEventListener('click', (e) => {
    const b = e.target.closest('button[data-z]');
    if (!b) return;
    const { W, H } = box2dNow();
    if (b.dataset.z === 'in') zoomAt(1.6, W / 2, H / 2, true);
    else if (b.dataset.z === 'out') zoomAt(1 / 1.6, W / 2, H / 2, true);
    else resetZoom(true);
  });

  // --- zoom durunca görünen alanın net görüntüsü ---
  let detailTimer = 0, detailToken = 0;
  function hideDetail() {
    detailToken++;
    clearTimeout(detailTimer);
    detailImg.classList.remove('is-on');
    if (chipExtra === DETAIL_MSG) { chipExtra = ''; refreshChip(); }
  }
  function scheduleDetail() {
    clearTimeout(detailTimer);
    if (Z.s < 1.3 || S.view !== '2d') return;          // az zoomda ana görüntü yeterince net
    if (P.playing) return;                               // oynatırken detay yok (duraklatınca gelir)
    detailTimer = setTimeout(loadDetail, 400);
  }
  async function loadDetail() {
    const t = ++detailToken;
    const [x0, y0, x1, y1] = regionBox();
    const sw = x1 - x0, sh = y1 - y0;
    // Kutuda görünen pencere (görüntü koordinatı 0–1) → boylam/enlem
    const u0 = -Z.ox / Z.s, u1 = (1 - Z.ox) / Z.s, v0 = -Z.oy / Z.s, v1 = (1 - Z.oy) / Z.s;
    const bbox = [x0 + u0 * sw, y1 - v1 * sh, x0 + u1 * sw, y1 - v0 * sh];
    const { W } = box2dNow();
    const url = texUrl(S.theme, activeIso(), Math.min(GLOBE_W_HI, widthFor(W * dpr())), bbox);
    chipExtra = DETAIL_MSG; refreshChip();
    let res;
    try { res = await getImage(url, true); } catch (e) { res = null; }
    if (t !== detailToken) return;
    chipExtra = ''; refreshChip();
    if (!res || !res.ok) return;
    markShown(res.src, detailImg.dataset.src);
    detailImg.dataset.src = res.src;
    detailImg.src = res.src;
    try { await detailImg.decode(); } catch (e) { /* yine de göster */ }
    if (t !== detailToken) return;
    detailImg.classList.add('is-on');
  }

  // ---------------- ses sistemine görünüm bildirimi (Faz 5) ----------------
  // world-sound müziği EKRANDA GÖRÜNEN piksellerden üretir. Bu yüzden her değişimde
  // 'eratone:view' olayı yayınlanır; eratone-audio.js bunu backend'e (/api/audio/source, /view) iletir.
  //   source: seslendirilecek görüntünün kutusu (2D: bölge kutusu, 3D: tüm dünya)
  //   box   : görünen kutu (2D: zoom penceresi; 3D yakın: bakılan alan; 3D uzak: bölge / dünya)
  /** Şu an görünen boylam/enlem kutusu [batı, güney, doğu, kuzey]. */
  function viewBox() {
    const [x0, y0, x1, y1] = regionBox();
    if (S.view === '2d') {
      const sw = x1 - x0, sh = y1 - y0;
      const u0 = -Z.ox / Z.s, u1 = (1 - Z.ox) / Z.s, v0 = -Z.oy / Z.s, v1 = (1 - Z.oy) / Z.s;
      return [x0 + u0 * sw, y1 - v1 * sh, x0 + u1 * sw, y1 - v0 * sh];
    }
    if (G) {
      const pov = G.pointOfView();
      if (pov.altitude < PATCH_MAX_ALT) {               // yakın: ekranda görünen alan (detay yamasıyla aynı hesap)
        const aspect = Math.max(1, stage.clientWidth / Math.max(1, stage.clientHeight));
        const cosLat = Math.max(0.2, Math.cos(pov.lat * Math.PI / 180));
        const h = Math.min(180, 2 * pov.altitude * 0.52 * 57.3);
        const w = Math.min(360, h * aspect / cosLat);
        const lat = clamp(pov.lat, -90 + h / 2, 90 - h / 2);
        const lng = clamp(((pov.lng + 540) % 360) - 180, -180 + w / 2, 180 - w / 2);
        return [lng - w / 2, lat - h / 2, lng + w / 2, lat + h / 2];
      }
    }
    return [x0, y0, x1, y1];                            // uzak 3D: seçili bölge (Dünya'da tüm dünya)
  }
  let viewTimer = 0;
  /** En çok 4 kez/sn yayınla (küre dönerken sürekli çağrılır; gecikmeli değil, aralıklı). */
  function emitView() {
    if (viewTimer) return;
    viewTimer = setTimeout(() => {
      viewTimer = 0;
      window.dispatchEvent(new CustomEvent('eratone:view', { detail: {
        theme: S.theme, date: activeIso(), region: regionSlug(), view: S.view,
        source: S.view === '2d' ? regionBox().slice() : [-180, -90, 180, 90],
        box: viewBox().map((v) => +v.toFixed(4)),
      } }));
    }, 250);
  }

  // ---------------- yerleşim: küre/harita orta sahneye sığsın ----------------
  function freeBox() {
    const cs = getComputedStyle(stage);
    const w = stage.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    const h = stage.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
    // üstte görünüm seçici (~60px), altta veri şeridi + bilgi satırı (~110px) için pay bırak
    return { w: Math.max(200, w - 48), h: Math.max(160, h - 170) };
  }
  /** 2D kutunun boyutu: bölgenin en/boy oranında, boş alana sığan en büyük dikdörtgen. */
  function box2d() {
    const { w, h } = freeBox();
    const [x0, y0, x1, y1] = regionBox();
    const ratio = (x1 - x0) / (y1 - y0);                 // görüntünün en/boy oranı (eşdikdörtgen)
    let bw = w, bh = w / ratio;
    if (bh > h) { bh = h; bw = h * ratio; }
    return { w: bw, h: bh };
  }
  function layout() {
    const full = S.view === '3d' && !!G;                 // gerçek küre: tuval tüm orta sahne
    stage.classList.toggle('ej-globe-full', full);
    if (S.view === '3d') {
      if (full) {
        el3d.style.width = el3d.style.height = '';
        if (globeStage) globeStage.style.width = globeStage.style.height = '';
        G.width(stage.clientWidth).height(stage.clientHeight);
      } else {                                           // WebGL yok: eski küçük CSS küre
        const { w, h } = freeBox();
        const d = Math.round(clamp(Math.min(w, h), 200, 760));
        el3d.style.width = el3d.style.height = d + 'px';
        if (globeStage) { globeStage.style.width = globeStage.style.height = (d + 40) + 'px'; }
      }
    } else {
      const { w: bw, h: bh } = box2d();
      el2d.style.width = Math.round(bw) + 'px';
      el2d.style.height = Math.round(bh) + 'px';
      el2d.style.maxWidth = 'none';
      if (globeStage) { globeStage.style.width = Math.round(bw) + 'px'; globeStage.style.height = Math.round(bh) + 'px'; }
      if (mapImg.isConnected) applyZ(false);             // kutu boyu değişti: zoom oranla korunur
    }
  }

  // ---------------- çizim ----------------
  let token = 0;
  let mapSrc = null;

  async function render() {
    const t = ++token;
    const reqIso = activeIso();
    chipExtra = '';      // önceki isteğin ek yazısı ("yüksek çözünürlük yükleniyor…") yeni karede kalmasın
    setChip(`NASA verisi alınıyor… <b>${esc(title(S.theme))}</b> · ${esc(fmt(reqIso))}`, 'loading');
    let res;
    try {
      if (S.view === '3d') {
        const hi = globeUrl(S.theme, reqIso, true);
        const lo = globeUrl(S.theme, reqIso, false);
        // İlerlemeli: 4096 önbellekte değilse önce 2048'i göster, 4096 gelince değiştir
        res = await getImage(isReady(hi) || hi === lo ? hi : lo, true);
        if (t !== token) return;
        if (res.ok && hi !== lo && !isReady(hi)) {
          getImage(hi, true).then((r) => {
            if (t !== token || S.view !== '3d') return;
            chipExtra = '';
            if (r.ok) applyGlobe(r.src);
            refreshChip();
          }).catch(() => { if (t === token) { chipExtra = ''; refreshChip(); } });
          chipExtra = 'yüksek çözünürlük yükleniyor…';
        }
      } else {
        res = await getImage(mapUrl(S.theme, reqIso), true);
      }
    } catch (err) {
      if (t !== token) return;
      setChip(`Görüntü alınamadı: ${esc(err.message || err)}`, 'error');
      return;
    }
    if (t !== token) return;                             // bu arada başka bir seçim yapıldı
    if (S.view === '3d') {
      if (!res.ok) { chipExtra = ''; setChip(`Küre görüntüsü alınamadı (HTTP ${res.status}) · ${esc(title(S.theme))} · ${esc(fmt(reqIso))}`, 'error'); return; }
      applyGlobe(res.src);
      patch.key = null;                                  // tema/tarih değişti: yamayı yenile
      if (P.playing) clearPatch();                       // eski tarihli yama yeni karenin üstünde kalmasın
      else schedulePatch();
    } else {
      markShown(res.src, mapSrc);
      mapSrc = res.src;
      if (!mapImg.isConnected) el2d.insertBefore(mapImg, el2d.firstChild);
      el2d.classList.add('has-map');
      mapImg.src = res.src;                              // hata olsa da göster: API hatayı yazılı görsel döndürür
      mapImg.alt = `${title(S.theme)} — ${S.region} — ${fmt(res.used || reqIso)}`;
      ensure2dUi();
      applyZ(false);                                     // zoom korunur; yeni tarih/tema için net görüntü yeniden çekilir
      if (!res.ok) { setChip(`Harita alınamadı (HTTP ${res.status}) · ayrıntı görselde`, 'error'); return; }
    }
    lastRes = res; lastReq = reqIso;
    setChip(describe(res, reqIso));
    emitView();                                          // Faz 5: tema/tarih/görünüm değişti → ses kaynağı
  }

  // ---------------- soldaki 6 kart ----------------
  let thumbToken = 0;
  function refreshThumbs() {
    const t = ++thumbToken;
    const d = S.range ? S.range.isos[0] : iso(S.date);
    cards.forEach((card) => {
      const slot = card.querySelector('.map-preview-slot');
      if (!slot) return;
      const theme = card.dataset.theme;
      slot.classList.add('is-loading');
      slot.classList.remove('is-error');
      if (!slot.querySelector('img')) slot.textContent = 'Yükleniyor…';
      getImage(texUrl(theme, d, THUMB_W, regionSlug()), false).then((res) => {
        if (t !== thumbToken) return;
        slot.classList.remove('is-loading');
        if (!res.ok) { slot.classList.add('is-error'); slot.classList.remove('has-img'); slot.textContent = 'Veri alınamadı'; slot.title = `HTTP ${res.status}`; return; }
        let img = slot.querySelector('img');
        if (!img) { slot.textContent = ''; img = document.createElement('img'); img.alt = ''; img.draggable = false; slot.appendChild(img); }
        markShown(res.src, img.dataset.src);
        img.dataset.src = res.src;
        img.src = res.src;
        slot.classList.add('has-img');
        const lim = limitsFor(theme);
        slot.title = `${title(theme)} · veri: ${fmt(res.used || d)}` + (lim ? ` · veri aralığı ${fmt(lim.min)} – ${fmt(lim.max)}` : '');
      }).catch(() => {
        if (t !== thumbToken) return;
        slot.classList.remove('is-loading');
        if (!slot.querySelector('img')) slot.textContent = '—';
      });
    });
  }

  // ---------------- aralık kareleri: arka planda önbelleğe al ----------------
  let rangeToken = 0;
  function prefetchRange() {
    if (!S.range) return;
    const t = ++rangeToken;
    // Oynatma sırasıyla: şu anki kareden ileri, sonra baştan (sıradaki kare önce gelsin)
    const n = S.range.isos.length, k0 = S.range.idx;
    const order = Array.from({ length: n }, (_, k) => S.range.isos[(k0 + k) % n]);
    const urls = Array.from(new Set(order.map((d) => viewUrl(S.theme, d))));
    S.range.total = urls.length;
    S.range.done = 0;
    urls.forEach((u) => {
      getImage(u, false, true).then(() => {
        if (t !== rangeToken || !S.range) return;
        S.range.done++;
        if (!chip.classList.contains('is-loading') && !chip.classList.contains('is-error')) refreshChip();
      }).catch(() => {});
    });
  }

  // ---------------- aralık oynatıcı ----------------
  // Aralık "Görüntüle" ile uygulanınca kareler KENDİLİĞİNDEN oynar (döngü). Sonraki kare yüklenmeden geçilmez
  // (boş/yarım kare gösterilmez; şerit "sonraki kare yükleniyor" der). Kareler eratone.html'deki kaydırıcı
  // üzerinden ilerletilir → üstteki tarih ve paneldeki kaydırıcı da aynı kareyi gösterir.
  // ◀ ▶ / kaydırıcıya elle dokunmak oynatmayı duraklatır. Ana ▶ (müzik) düğmesinden bağımsızdır.
  const SPEEDS = [
    { ms: 2000, label: '0.5 kare/sn' }, { ms: 1000, label: '1 kare/sn' },
    { ms: 500, label: '2 kare/sn' }, { ms: 250, label: '4 kare/sn' },
  ];
  const ICON_PLAY = '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true"><path d="M8.5 5.6v12.8a1 1 0 0 0 1.5.86l10.2-6.4a1 1 0 0 0 0-1.72L10 4.74a1 1 0 0 0-1.5.86z"/></svg>';
  const ICON_PAUSE = '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true"><rect x="6.5" y="5" width="4" height="14" rx="1.3"/><rect x="13.5" y="5" width="4" height="14" rx="1.3"/></svg>';
  const player = document.createElement('div');
  player.className = 'ej-player';
  player.hidden = true;
  player.innerHTML = '<button type="button" class="ej-pl-play"></button>'
    + '<span class="ej-pl-label"></span>'
    + '<button type="button" class="ej-pl-speed" title="Oynatma hızı (tıkla: değiştir)"></button>';
  stage.appendChild(player);
  const plPlay = player.querySelector('.ej-pl-play');
  const plLabel = player.querySelector('.ej-pl-label');
  const plSpeed = player.querySelector('.ej-pl-speed');
  const failed = new Set();                              // alınamayan kare URL'leri: beklemeden geçilir
  const SKIP_MS = 5000;                                  // sıradaki kare bundan uzun gecikirse hazır olana atla
  const frameUrl = (j) => viewUrl(S.theme, S.range.isos[j]);

  function paintPlayer() {
    player.hidden = !S.range;
    if (!S.range) return;
    plPlay.innerHTML = P.playing ? ICON_PAUSE : ICON_PLAY;
    plPlay.title = P.playing ? 'Duraklat' : 'Kareleri oynat';
    plPlay.setAttribute('aria-label', plPlay.title);
    plPlay.classList.toggle('is-on', P.playing);
    const n = S.range.isos.length;
    plLabel.textContent = `Kare ${S.range.idx + 1}/${n} · ${fmt(S.range.isos[S.range.idx])}`
      + (P.waiting ? ' · sonraki kare yükleniyor…' : '');
    plLabel.classList.toggle('is-wait', !!P.waiting);
    plSpeed.textContent = SPEEDS[P.speed].label;
  }
  function goFrame(j) {
    const sl = document.getElementById('frame-slider');
    P.self = true;
    try {
      if (sl) { sl.value = String(j + 1); sl.dispatchEvent(new Event('input', { bubbles: true })); }
      else { S.range.idx = j; render(); }
    } finally { P.self = false; }
    paintPlayer();
  }
  function tick() {
    clearTimeout(P.timer);
    if (!P.playing || !S.range) return;
    const n = S.range.isos.length;
    let next = (S.range.idx + 1) % n;
    const url = frameUrl(next);
    if (!isReady(url) && !failed.has(url)) {
      if (P.waiting !== url) {                           // bir kez öne al; hata verirse atla
        P.waiting = url;
        P.waitSince = performance.now();
        getImage(url, true).then((r) => { if (!r.ok) failed.add(url); }, () => failed.add(url));
        paintPlayer();
      }
      // NASA bazen tek bir kareyi çok geciktiriyor: SKIP_MS'den uzun sürerse hazır olan sonraki kareye atla.
      // Geciken kare arka planda yüklenmeye devam eder, sonraki turda gösterilir.
      const ahead = performance.now() - P.waitSince > SKIP_MS
        ? Array.from({ length: n - 2 }, (_, k) => (next + 1 + k) % n).find((j) => isReady(frameUrl(j)))
        : undefined;
      if (ahead === undefined) { P.timer = setTimeout(tick, 120); return; }
      next = ahead;
    }
    P.waiting = null;
    goFrame(next);
    P.timer = setTimeout(tick, SPEEDS[P.speed].ms);
  }
  function play() {
    if (!S.range || S.range.isos.length < 2) return;
    P.playing = true;
    clearPatch(); hideDetail();
    paintPlayer();
    P.timer = setTimeout(tick, SPEEDS[P.speed].ms);     // ilk kare ekranda bir süre kalsın
  }
  function pause() {
    clearTimeout(P.timer);
    const was = P.playing;
    P.playing = false; P.waiting = null;
    paintPlayer();
    if (was) { schedulePatch(); scheduleDetail(); }      // durunca net görüntüler geri gelsin
  }
  plPlay.addEventListener('click', () => (P.playing ? pause() : play()));
  plSpeed.addEventListener('click', () => { P.speed = (P.speed + 1) % SPEEDS.length; paintPlayer(); });

  // ---------------- olaylar ----------------
  cards.forEach((card) => {
    const pick = () => {
      if (card.dataset.theme === S.theme) return;
      S.theme = card.dataset.theme;
      S.clampNote = '';
      applyLimits();                                     // Faz 3: tarih seçiciyi temanın veri aralığına sınırla
      cancelBackground();
      clearPatch();
      render();
      prefetchRange();
    };
    card.addEventListener('click', pick);
    card.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); card.click(); } });
  });

  document.querySelectorAll('.region-item[data-region]').forEach((item) => {
    item.addEventListener('click', () => {
      const r = item.getAttribute('data-region');
      if (!REGIONS[r] || r === S.region) return;
      S.region = r;
      resetZoom(false);                                  // 2D zoom: farklı bölge = farklı kutu → sığdır
      cancelBackground();
      aimGlobe(1200);
      layout();
      if (S.view === '2d') render(); else { refreshChip(); schedulePatch(); emitView(); }   // küre aynı doku; sadece döner
      refreshThumbs();
      prefetchRange();
    });
  });

  function setView(v) {
    if (S.view === v) return;
    S.view = v;
    if (G) { if (v === '3d') G.resumeAnimation(); else G.pauseAnimation(); }
    if (v !== '3d') clearPatch();
    if (v !== '2d') hideDetail();
    requestAnimationFrame(() => { layout(); render(); prefetchRange(); });
  }
  if (btn3d) btn3d.addEventListener('click', () => setView('3d'));
  if (btn2d) btn2d.addEventListener('click', () => setView('2d'));

  // Üstteki "Görüntüle": silindirdeki tek tarihi uygula (aralık görünümü kapanır)
  window.addEventListener('eratone:date-applied', (e) => {
    const d = parseIso(e.detail && e.detail.date);
    if (!d) return;
    S.date = d;
    S.clampNote = '';
    pause();
    S.range = null;
    paintPlayer();                                       // aralık yok → oynatıcı gizlenir
    rangeToken++;
    cancelBackground();
    render();
    refreshThumbs();
  });

  // Aralık paneli "Görüntüle": kare tarihleri eratone.html rebuildFrames()'ten gelir
  window.addEventListener('eratone:range-applied', (e) => {
    const isos = (e.detail && e.detail.frames) || [];
    if (!isos.length) return;
    pause();
    S.range = { isos, idx: 0, done: 0, total: 0 };
    S.clampNote = '';
    failed.clear();
    cancelBackground();
    render();
    prefetchRange();
    refreshThumbs();
    play();                                              // aralık seçilince kareler kendiliğinden oynar
  });

  // Kare kaydırıcısı / ◀ ▶ (eratone.html showFrame bu olayı yayınlar)
  window.addEventListener('eratone:frame', (e) => {
    if (!S.range || !e.detail) return;
    const i = S.range.isos.indexOf(e.detail.date);       // uygulanmamış (panelde düzenlenen) aralığı yok say
    if (i < 0 || i === S.range.idx) return;
    if (!P.self && P.playing) pause();                   // elle ◀ ▶ / kaydırıcı → oynatma durur
    S.range.idx = i;
    render();
    paintPlayer();
  });

  // Yan paneller açılıp kapanınca / pencere boyutu değişince yeniden sığdır
  if ('ResizeObserver' in window) new ResizeObserver(() => { layout(); schedulePatch(); }).observe(stage);
  else window.addEventListener('resize', layout);

  // ---------------- açılış ----------------
  if (S.view === '3d') initGlobe();
  // 2D'den başlanırsa küre ilk 3D geçişinde kurulur
  else if (btn3d) btn3d.addEventListener('click', () => { if (!G && !flat) { initGlobe(); aimGlobe(0); layout(); render(); } }, { once: true });

  layout();
  aimGlobe(0);
  render();                // açılış: seçili tema, DÜN, Dünya
  refreshThumbs();         // ardından 6 kartın önizlemeleri (düşük öncelik)

  // Tema bilgileri (başlık + gerçek veri aralığı) → tarih sınırları
  fetch('/api/themes').then((r) => r.json()).then((list) => {
    list.forEach((t) => {
      S.titles[t.id] = t.title;
      S.info[t.id] = { first: t.first, last: t.last, unit: t.unit, step: t.step };
    });
    if (applyLimits()) render();                         // açılış tarihi bu temanın aralığı dışındaysa
    refreshChip();
  }).catch(() => {});

  window.eratoneData = { state: S, render, refreshThumbs, limitsFor };   // hata ayıklama / müzik kiti için okuma amaçlı

  // ---------------- test kancası (yalnızca adreste ?ej=1 varsa) ----------------
  // Kullanıcı tıklamalarını taklit eder; normal açılışta HİÇBİR etkisi yoktur. Örnek:
  //   /?ej=1&theme=sicaklik&region=Türkiye&view=2d&range=2025-01-01,2025-12-31,6&frame=3
  //   /?ej=1&pov=39,35,0.45   (küreyi lat,lng,irtifa'ya götürür — zoom/detay yaması testi)
  //   /?ej=1&sizes=5          (5 sn'de bir boyutları konsola yazar)
  (function testHook() {
    const q = new URLSearchParams(location.search);
    if (q.get('ej') !== '1') return;
    const click = (sel) => { const n = document.querySelector(sel); if (n) n.click(); };
    if (q.get('theme')) click(`.map-card[data-theme="${q.get('theme')}"]`);
    if (q.get('region')) click(`.region-item[data-region="${q.get('region')}"]`);
    if (q.get('view') === '2d') click('#btn-view-2d');
    const rg = (q.get('range') || '').split(',');
    if (rg.length === 3) setTimeout(() => {               // rdelay=ms: açılış yüklemeleri bittikten sonra uygula
      document.getElementById('range-start').value = rg[0];
      document.getElementById('range-end').value = rg[1];
      document.getElementById('range-frames').value = rg[2];
      // birleşik Görüntüle: aralık modunu aç, üstteki Görüntüle'ye bas (eski #btn-view-range gizli)
      if (typeof window.eratoneSetRangeMode === 'function') { window.eratoneSetRangeMode(true); click('#btn-view-date'); }
      else click('#btn-view-range');
      for (let k = 0; k < (parseInt(q.get('frame'), 10) || 0); k++) click('#frame-next');
    }, parseInt(q.get('rdelay'), 10) || 0);
    // three=1: küre çizicisinin Three.js sürümü (girişin r128'i globe.gl'e sızıyor mu? — renk hatası testi)
    if (q.get('three')) setTimeout(() => { const R = G && G.renderer(); console.log('[ej-test] window.THREE', typeof window.THREE,
      'outputColorSpace', R && R.outputColorSpace, 'outputEncoding', R && R.outputEncoding, '__THREE__', window.__THREE__); }, 4000);
    // Seslendirme testi: voice=tr_female|tr_male → 4 sn'de o düğmeye bas; vtheme=<tema> → 12 sn'de haritayı
    // değiştir (otomatik anlatım); vlog=1 → saniyede bir altyazı + konuşan düğme durumu konsola
    if (q.get('voice')) setTimeout(() => {
      const p = document.querySelector(`.voice-pill[data-voice="${q.get('voice')}"]`);
      if (p && p.classList.contains('active')) p.click();          // önce kapat (varsayılan Erkek açık)
      if (p) p.click();
    }, 4000);
    if (q.get('vtheme')) setTimeout(() => click(`.map-card[data-theme="${q.get('vtheme')}"]`), 12000);
    // vregion=<bölge etiketi> (+ vregion_at=ms, varsayılan 15000) → çalarken bölge değiştirme testi
    if (q.get('vregion')) setTimeout(() => click(`.region-item[data-region="${q.get('vregion')}"]`),
      parseInt(q.get('vregion_at'), 10) || 15000);
    // vdate=1 → 6 sn'de tarih okuna bas (Görüntüle'den önce tarih anlatımı); veq=1 → 14 sn'de ekolayzer panelini
    // aç, 24 sn'de bas bandını +3 dB yap (ekolayzer anlatımı)
    if (q.get('vdate')) setTimeout(() => click('#btn-wheel-up'), 6000);
    if (q.get('veq')) {
      setTimeout(() => click('#btn-toggle-eq'), 14000);
      setTimeout(() => { const s = document.querySelector('.eq-slider[data-target="val-60hz"]');
        if (s) { s.value = '3'; s.dispatchEvent(new Event('input', { bubbles: true })); s.dispatchEvent(new Event('change', { bubbles: true })); }
        const m = document.querySelector('.mix-slider[data-inst="piano"]');       // enstrüman ses düzeyi (kalıcılık testi)
        if (m) { m.value = '55'; m.dispatchEvent(new Event('input', { bubbles: true })); m.dispatchEvent(new Event('change', { bubbles: true })); } }, 24000);
    }
    // vinst=<enstrüman> → 30 sn'de o enstrüman düğmesine bas (enstrüman duyurusu testi)
    if (q.get('vinst')) setTimeout(() => click(`.instrument-pill[data-inst="${q.get('vinst')}"]`), 30000);
    if (q.get('vlog')) { const t0 = performance.now(); setInterval(() => {
      const c = document.querySelector('.ej-voice-caption'), sp = document.querySelector('.voice-pill.is-speaking');
      console.log('[ej-test] t', ((performance.now() - t0) / 1000).toFixed(0), 'konusan', sp ? sp.dataset.voice : '-',
        'altyazi', c && !c.hidden ? c.textContent.slice(0, 90) : '-');
    }, 1000); }
    // rpanel=ms: tarih aralığı panelini bu kadar sonra aç (aralık modu anahtarını görmek için)
    if (q.get('rpanel')) setTimeout(() => click('#btn-range'), parseInt(q.get('rpanel'), 10) || 3000);
    // Oynatıcı testi: plog=1 → saniyede bir kare/oynatma/önbellek durumu konsola (t = açılıştan beri sn)
    if (q.get('plog')) { const t0 = performance.now(); setInterval(() => {
      if (S.range) console.log('[ej-test] t', ((performance.now() - t0) / 1000).toFixed(1), 'kare', S.range.idx + 1, '/', S.range.isos.length,
        'oynuyor', P.playing, 'bekliyor', !!P.waiting, 'onbellek', S.range.done, '/', S.range.total, 'kuyruk', Q.items.length, 'calisan', Q.running);
    }, 1000); }
    // tarih seçici ızgarasını aç (gün/ay/yıl) — kapalı (seçilemez) öğeleri görmek için
    if (q.get('picker') && typeof window.openPicker === 'function') setTimeout(() => {
      const anchor = { day: 'drum-day', month: 'drum-month', year: 'cylinder-viewport' }[q.get('picker')];
      window.openPicker(q.get('picker'), document.getElementById(anchor));
    }, 7000);   // tema aralıkları (/api/themes) geldikten SONRA: sınır değişince açık seçici kapanır
    // 2D zoom testi: z2d=ölçek,u,v (u,v: kutu içinde 0–1 konum) — 2D görüntü geldikten sonra
    const zz = (q.get('z2d') || '').split(',').map(Number);
    if (zz.length === 3) setTimeout(() => { const { W, H } = box2dNow(); zoomAt(zz[0], zz[1] * W, zz[2] * H, false); }, 6000);
    // Gerçek olay yolu testi: wheel=n (kutu ortasında n kez tekerlek ileri), pan=dx,dy (sürükleme pikseli)
    if (q.get('wheel')) setTimeout(() => {
      const r = el2d.getBoundingClientRect();
      const at = { clientX: r.left + r.width * 0.6, clientY: r.top + r.height * 0.4, bubbles: true, cancelable: true };
      for (let k = 0; k < +q.get('wheel'); k++) el2d.dispatchEvent(new WheelEvent('wheel', { ...at, deltaY: -100, deltaMode: 0 }));
      const pn = (q.get('pan') || '').split(',').map(Number);
      if (pn.length === 2) {
        el2d.dispatchEvent(new PointerEvent('pointerdown', { ...at, button: 0, pointerId: 1 }));
        el2d.dispatchEvent(new PointerEvent('pointermove', { ...at, clientX: at.clientX + pn[0], clientY: at.clientY + pn[1], pointerId: 1 }));
        el2d.dispatchEvent(new PointerEvent('pointerup', { ...at, clientX: at.clientX + pn[0], clientY: at.clientY + pn[1], pointerId: 1 }));
      }
      console.log('[ej-test] zoom', JSON.stringify(Z), 'cls', el2d.className, 'ui', zoomVal.textContent);
    }, 6000);
    // ses testi: play=1 → 5 sn sonra Oynat'a bas (ilk Çal: arayüz ayarları /api/audio'ya toplu gider)
    if (q.get('play') === '1') setTimeout(() => click('#btn-main-play'), 5000);
    const pv = (q.get('pov') || '').split(',').map(Number);
    if (pv.length === 3 && G) setTimeout(() => { G.controls().autoRotate = false; G.pointOfView({ lat: pv[0], lng: pv[1], altitude: pv[2] }, 0); schedulePatch(); }, 1500);
    if (q.get('sizes')) setInterval(() => {
      const r = (n) => { if (!n) return null; const b = n.getBoundingClientRect(); return `${Math.round(b.left)},${Math.round(b.top)} ${Math.round(b.width)}x${Math.round(b.height)}`; };
      const cv = el3d.querySelector('canvas');
      console.log('[ej-test] el3d', r(el3d), '| canvas', r(cv), cv ? `attr ${cv.width}x${cv.height}` : '',
        '| stage', r(stage), '| pov', G ? JSON.stringify(G.pointOfView()) : '-', '| patch', patch.key || '-',
        '| limits', JSON.stringify(limitsFor(S.theme)), '| date', iso(S.date),
        '| soluk silindir öğesi', document.querySelectorAll('.cylinder-item.is-out').length,
        '| silindir', Array.from(document.querySelectorAll('.cylinder-item.active')).map((x) => x.textContent + (x.classList.contains('is-out') ? '(OUT)' : '')).join(' '),
        '| seçici', (() => { const dp = document.querySelector('.date-picker'); return dp ? `${dp.className} öğe=${dp.children.length} kapalı=${dp.querySelectorAll('button:disabled').length} ${r(dp)}` : 'yok'; })(),
        '| openPicker', typeof window.openPicker);
    }, (parseInt(q.get('sizes'), 10) || 4) * 1000);
  })();
})();
