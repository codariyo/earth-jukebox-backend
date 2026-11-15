"""
World Sound — Test Uygulaması

worldsound kütüphanesini denemek için arayüz. Tüm müzik mantığı kütüphanededir;
bu dosya yalnızca MapSonifier'ı kullanır (diğer uygulamanız da aynısını yapacak).

Harita üzerinde:
    Fare tekerleği  : imlecin olduğu yere yakınlaş / uzaklaş
    Sol tık sürükle : haritayı kaydır
    Çift tık        : tüm haritaya dön
"""

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
from PIL import Image, ImageTk

from worldsound import (GIBS_LAYERS, MapSonifier, NasaGibsSource, Scale,
                        NOTE_NAMES_TR, note_name)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")

BG, PANEL, PANEL2 = "#0f172a", "#1e293b", "#0b1222"
FG, MUTED, ACCENT = "#e2e8f0", "#94a3b8", "#38bdf8"
NODATA_RGB = (24, 24, 30)
MAP_MAX_W, MAP_MAX_H = 860, 440


def find_images():
    out = []
    for folder in (BASE_DIR, os.path.join(BASE_DIR, "samples")):
        if os.path.isdir(folder):
            for f in sorted(os.listdir(folder)):
                if f.lower().endswith(IMAGE_EXT):
                    out.append(os.path.join(folder, f))
    return out


class WorldSoundTestApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("World Sound — Test Uygulaması")
        root.configure(bg=BG)

        self.son = MapSonifier()
        self.map_img = None          # görüntülenecek RGB PIL
        self.tk_img = None
        self._drawn_view = None
        self._drag = None
        self.canvas_w, self.canvas_h = MAP_MAX_W, MAP_MAX_H // 2 * 1
        self.show_grid = tk.BooleanVar(value=False)

        self._style()
        self._build_toolbar()
        body = tk.Frame(root, bg=BG)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        left = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both", expand=True)
        right = tk.Frame(body, bg=BG)
        right.pack(side="right", fill="y", padx=(10, 0))
        self._build_map(left)
        self._build_info(left)
        self._build_instruments(right)
        self._build_scan_settings(right)
        self._build_eq(root)

        try:
            self.son.start_audio()
        except Exception as ex:
            messagebox.showerror("Ses aygıtı", f"Ses çıkışı açılamadı:\n{ex}")

        imgs = find_images()
        if imgs:
            self.file_combo.set(os.path.relpath(imgs[0], BASE_DIR))
            self.load_path(imgs[0])
        self._tick()

    # ================================================================== arayüz kurulumu
    def _style(self):
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("TCombobox", fieldbackground=PANEL, background=PANEL, foreground=FG,
                     arrowcolor=FG, bordercolor=PANEL)
        self.root.option_add("*TCombobox*Listbox.background", PANEL)
        self.root.option_add("*TCombobox*Listbox.foreground", FG)

    def _btn(self, parent, text, cmd, color="#2563eb"):
        return tk.Button(parent, text=text, command=cmd, bg=color, fg="white", relief="flat",
                         activebackground=color, font=("Segoe UI", 9, "bold"), padx=10, pady=4)

    def _label(self, parent, text, color=MUTED, size=8, bold=False, **kw):
        return tk.Label(parent, text=text, bg=parent["bg"], fg=color,
                        font=("Segoe UI", size, "bold" if bold else "normal"), **kw)

    def _build_toolbar(self):
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=10, pady=8)

        self._btn(bar, "📂 Görsel Seç (PNG/JPG)", self.choose_file).pack(side="left")
        self.file_combo = ttk.Combobox(bar, width=38, state="readonly",
                                       values=[os.path.relpath(p, BASE_DIR) for p in find_images()])
        self.file_combo.pack(side="left", padx=6)
        self.file_combo.bind("<<ComboboxSelected>>",
                             lambda e: self.load_path(os.path.join(BASE_DIR, self.file_combo.get())))

        tk.Frame(bar, bg="#334155", width=2, height=26).pack(side="left", padx=8)
        self.layer_combo = ttk.Combobox(bar, width=40, state="readonly", values=[l.title for l in GIBS_LAYERS])
        self.layer_combo.current(2)
        self.layer_combo.pack(side="left")
        self._label(bar, "Tarih:").pack(side="left", padx=(6, 2))
        self.date_var = tk.StringVar(value="")
        tk.Entry(bar, textvariable=self.date_var, width=11, bg=PANEL, fg=FG, insertbackground=FG,
                 relief="flat").pack(side="left")
        self._label(bar, "(boş = en son)").pack(side="left", padx=(2, 6))
        self._btn(bar, "🛰 NASA'dan Çek", self.fetch_nasa, "#0284c7").pack(side="left")
        self.detail_btn = self._btn(bar, "🔍 Görünen Bölgeyi Detaylı Çek", self.fetch_detail, "#0369a1")
        self.detail_btn.pack(side="left", padx=6)

        self.play_btn = self._btn(bar, "▶ Çal", self.toggle_play, "#10b981")
        self.play_btn.pack(side="right")
        self._btn(bar, "⟲ Tüm Harita", self.reset_view, "#475569").pack(side="right", padx=6)

    def _build_map(self, parent):
        self.canvas = tk.Canvas(parent, width=MAP_MAX_W, height=MAP_MAX_H // 2, bg=PANEL2,
                                highlightthickness=0, cursor="fleur")
        self.canvas.pack(anchor="w")
        self.canvas.bind("<MouseWheel>", self._on_wheel)              # Windows / macOS
        self.canvas.bind("<Button-4>", lambda e: self._wheel_zoom(e, 1.25))   # Linux
        self.canvas.bind("<Button-5>", lambda e: self._wheel_zoom(e, 0.8))
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<Double-Button-1>", lambda e: self.reset_view())

        self.legend = tk.Canvas(parent, width=MAP_MAX_W, height=34, bg=BG, highlightthickness=0)
        self.legend.pack(anchor="w", pady=(4, 0))

    def _build_info(self, parent):
        box = tk.Frame(parent, bg=PANEL, padx=10, pady=6)
        box.pack(fill="x", pady=6)
        self.view_lbl = self._label(box, "", FG, 9, anchor="w", justify="left")
        self.view_lbl.pack(fill="x")
        self.notes_lbl = tk.Label(box, text="", bg=PANEL, fg=ACCENT, font=("Consolas", 12, "bold"), anchor="w")
        self.notes_lbl.pack(fill="x", pady=(4, 0))
        self.filter_lbl = self._label(box, "", MUTED, 9, anchor="w", justify="left")
        self.filter_lbl.pack(fill="x")
        row = tk.Frame(box, bg=PANEL)
        row.pack(fill="x", pady=(4, 0))
        tk.Checkbutton(row, text="Tarama ızgarasını göster", variable=self.show_grid, bg=PANEL, fg=FG,
                       selectcolor=PANEL2, activebackground=PANEL, activeforeground=ACCENT,
                       font=("Segoe UI", 8), command=lambda: setattr(self, "_drawn_view", None)).pack(side="left")
        self.status_lbl = self._label(row, "", "#fbbf24", 8)
        self.status_lbl.pack(side="right")

    def _build_instruments(self, parent):
        fr = tk.LabelFrame(parent, text=" Enstrümanlar (her nota açık olanların hepsinde çalar) ",
                           bg=BG, fg=MUTED, font=("Segoe UI", 9, "bold"), padx=8, pady=4)
        fr.pack(fill="x")
        self._label(fr, "Açık   Enstrüman           Ses                 Oktav").grid(row=0, column=0, columnspan=4, sticky="w")
        for r, inst in enumerate(self.son.instruments, start=1):
            var = tk.BooleanVar(value=inst.enabled)
            tk.Checkbutton(fr, variable=var, bg=BG, selectcolor=PANEL, activebackground=BG,
                           command=lambda k=inst.key, v=var: self.son.set_instrument(k, enabled=v.get())
                           ).grid(row=r, column=0)
            self._label(fr, inst.label, FG, 9, width=13, anchor="w").grid(row=r, column=1, sticky="w")
            sc = tk.Scale(fr, from_=0, to=100, orient="horizontal", length=120, showvalue=False,
                          bg=BG, troughcolor=PANEL, highlightthickness=0, sliderrelief="flat",
                          command=lambda v, k=inst.key: self.son.set_instrument(k, volume=float(v) / 100))
            sc.set(int(inst.volume * 100))
            sc.grid(row=r, column=2, padx=4)
            sp = tk.Spinbox(fr, from_=-3, to=3, width=3, bg=PANEL, fg=FG, buttonbackground=PANEL,
                            relief="flat", justify="center")
            sp.delete(0, "end")
            sp.insert(0, str(inst.octave))
            sp.config(command=lambda k=inst.key, s=sp: self.son.set_instrument(k, octave=int(s.get())))
            sp.grid(row=r, column=3)

    def _slider(self, parent, label, lo, hi, init, cmd, res=1.0, fmt="{:.0f}"):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=1)
        self._label(row, label, FG, 8, width=19, anchor="w").pack(side="left")
        val = self._label(row, "", ACCENT, 8, width=7)
        def on(v):
            val.config(text=fmt.format(float(v)))
            cmd(float(v))
        s = tk.Scale(row, from_=lo, to=hi, resolution=res, orient="horizontal", length=150,
                     showvalue=False, bg=BG, troughcolor=PANEL, highlightthickness=0, command=on)
        s.set(init)
        s.pack(side="left")
        val.pack(side="left")
        return s

    def _build_scan_settings(self, parent):
        fr = tk.LabelFrame(parent, text=" Tarama ve Nota Ayarları ", bg=BG, fg=MUTED,
                           font=("Segoe UI", 9, "bold"), padx=8, pady=4)
        fr.pack(fill="x", pady=(8, 0))

        # Sabit ayarlar
        self.son.set_scan_speed(5)
        self.son.set_max_voices(10)
        self.son.set_reverb(0.25)
        self.son.set_master(0.8)
        for text in ("Tarama hızı: 5 sütun/sn", "Aynı anda en çok nota: 10", "Yankı: %25"):
            self._label(fr, text, FG, 8).pack(anchor="w", pady=1)

    def _build_eq(self, parent):
        fr = tk.LabelFrame(parent, text=" 5 Bant Ekolayzer  ·  Frekans Eğrisi  ·  Canlı Spektrum ",
                           bg=BG, fg=MUTED, font=("Segoe UI", 9, "bold"), padx=8, pady=4)
        fr.pack(fill="x", padx=10, pady=(0, 10))
        sliders = tk.Frame(fr, bg=BG)
        sliders.pack(side="left")
        self.eq_scales = {}
        for band in self.son.equalizer.bands:
            col = tk.Frame(sliders, bg=BG)
            col.pack(side="left", padx=5)
            val = self._label(col, "0.0 dB", ACCENT, 8)
            val.pack()
            def on(v, k=band.key, lbl=val):
                self.son.set_eq(k, float(v))
                lbl.config(text=f"{float(v):+.1f} dB")
                self._draw_eq_curve()
            s = tk.Scale(col, from_=12, to=-12, resolution=0.5, orient="vertical", length=110,
                         showvalue=False, bg=BG, troughcolor=PANEL, highlightthickness=0, command=on)
            s.set(0)
            s.pack()
            self.eq_scales[band.key] = s
            hz = f"{band.freq / 1000:g}k" if band.freq >= 1000 else f"{band.freq:g}"
            self._label(col, f"{band.label}\n{hz} Hz", FG, 8, justify="center").pack()
        self._btn(sliders, "Sıfırla", self._eq_reset, "#475569").pack(side="left", padx=8)

        self.eq_canvas = tk.Canvas(fr, width=330, height=150, bg=PANEL2, highlightthickness=0)
        self.eq_canvas.pack(side="left", padx=8)
        self.spec_canvas = tk.Canvas(fr, width=420, height=150, bg=PANEL2, highlightthickness=0)
        self.spec_canvas.pack(side="left", padx=4)
        self._draw_eq_curve()

    # ================================================================== eylemler
    def choose_file(self):
        path = filedialog.askopenfilename(
            initialdir=BASE_DIR, title="Harita görseli seç",
            filetypes=[("Görseller", " ".join("*" + e for e in IMAGE_EXT)), ("PNG", "*.png"), ("Tümü", "*.*")])
        if path:
            self.load_path(path)

    def load_path(self, path):
        try:
            self._after_load(self.son.load(path))
        except Exception as ex:
            messagebox.showerror("Görsel okunamadı", f"{path}\n\n{ex}")

    def _after_load(self, data):
        rgba = data.rgba
        rgb = rgba[..., :3] * rgba[..., 3:4] + (np.array(NODATA_RGB) / 255.0) * (1 - rgba[..., 3:4])
        self.map_img = Image.fromarray((rgb * 255 + 0.5).astype(np.uint8), "RGB")
        scale = min(MAP_MAX_W / data.width, MAP_MAX_H / data.height)
        self.canvas_w = max(200, int(data.width * scale))
        self.canvas_h = max(100, int(data.height * scale))
        self.canvas.config(width=self.canvas_w, height=self.canvas_h)
        self.legend.config(width=self.canvas_w)
        self._drawn_view = None
        self._draw_legend()
        nodata = float((rgba[..., 3] < 0.5).mean())
        self.status_lbl.config(text=f"Yüklendi: {data.name}  ·  {data.width}x{data.height} px"
                               + (f"  ·  ölçüm yok: %{nodata * 100:.0f}" if nodata > 0.001 else ""))

    def fetch_nasa(self):
        layer = GIBS_LAYERS[self.layer_combo.current()]
        date = self.date_var.get().strip() or None
        self._run_bg(f"NASA'dan indiriliyor: {layer.title} ...",
                     lambda: NasaGibsSource(layer.layer_id, date, width=2048).load())

    def fetch_detail(self):
        if self.son.map is None or self.son.map.meta.get("source") != "gibs":
            messagebox.showinfo("Detaylı çekim", "Bu özellik NASA'dan çekilen haritalarda çalışır.\n"
                                "Önce 'NASA'dan Çek' ile bir katman yükleyin, sonra yakınlaştırın.")
            return
        self._run_bg("Görünen bölge NASA'dan yüksek çözünürlükte çekiliyor ...",
                     lambda: self.son.fetch_visible_region_from_nasa(width=2048), loaded=True)

    def _run_bg(self, msg, job, loaded=False):
        self.status_lbl.config(text=msg)

        def work():
            try:
                data = job()
                if not loaded:
                    self.son.load(data)
                self.root.after(0, lambda: self._after_load(self.son.map))
            except Exception as ex:
                err = str(ex)[:300]
                self.root.after(0, lambda: (self.status_lbl.config(text="Hata"),
                                            messagebox.showerror("NASA", err)))
        threading.Thread(target=work, daemon=True).start()

    def toggle_play(self):
        if self.son.is_playing:
            self.son.pause()
        else:
            self.son.play()
        self._update_play_btn()

    def _update_play_btn(self):
        on = self.son.is_playing
        self.play_btn.config(text="⏸ Durdur" if on else "▶ Çal", bg="#f59e0b" if on else "#10b981",
                             activebackground="#f59e0b" if on else "#10b981")

    def reset_view(self):
        self.son.reset_view()

    def _eq_reset(self):
        for s in self.eq_scales.values():
            s.set(0)

    # ================================================================== fare
    def _canvas_to_map(self, x, y):
        v = self.son.viewport
        return v.x0 + (x / self.canvas_w) * v.width, v.y0 + (y / self.canvas_h) * v.height

    def _on_wheel(self, e):
        self._wheel_zoom(e, 1.25 if e.delta > 0 else 0.8)

    def _wheel_zoom(self, e, factor):
        if self.son.map is None:
            return
        cx, cy = self._canvas_to_map(e.x, e.y)
        self.son.zoom(factor, cx, cy)

    def _on_press(self, e):
        self._drag = (e.x, e.y)

    def _on_drag(self, e):
        if self._drag is None or self.son.map is None:
            return
        dx, dy = e.x - self._drag[0], e.y - self._drag[1]
        self._drag = (e.x, e.y)
        v = self.son.viewport
        self.son.pan(-dx / self.canvas_w * v.width, -dy / self.canvas_h * v.height)

    # ================================================================== çizim
    def _draw_map(self):
        data = self.son.map
        if data is None or self.map_img is None:
            return
        v = self.son.viewport
        box = data.pixel_box(*v.as_tuple())
        crop = self.map_img.crop(box)
        px_per_cell = self.canvas_w / max(1, box[2] - box[0])
        method = Image.NEAREST if px_per_cell >= 3 else Image.BILINEAR
        self.tk_img = ImageTk.PhotoImage(crop.resize((self.canvas_w, self.canvas_h), method))
        self.canvas.delete("map")
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_img, tags="map")
        self.canvas.tag_lower("map")

        self.canvas.delete("grid")
        g = self.son.grid
        if self.show_grid.get() and g is not None:
            for i in range(1, g.rows):
                y = i * self.canvas_h / g.rows
                self.canvas.create_line(0, y, self.canvas_w, y, fill="#334155", tags="grid")
            for j in range(1, g.cols):
                x = j * self.canvas_w / g.cols
                self.canvas.create_line(x, 0, x, self.canvas_h, fill="#334155", tags="grid")

    def _draw_overlay(self):
        self.canvas.delete("ov")
        g = self.son.grid
        if g is None:
            return
        cw, ch = self.canvas_w / g.cols, self.canvas_h / g.rows
        step = self.son.last_step
        if self.son.is_playing and step is not None and step.cols == g.cols:
            x0 = step.column * cw
            self.canvas.create_rectangle(x0, 0, x0 + cw, self.canvas_h, outline="", fill="#ffffff",
                                         stipple="gray12", tags="ov")
            # çalan notaların hücreleri: aynı notayı veren bitişik hücreler tek kutu
            for midi, note in step.sounding.items():
                rows = sorted(note.rows)
                runs, start = [], rows[0] if rows else None
                for a, b in zip(rows, rows[1:] + [None]):
                    if b != a + 1:
                        runs.append((start, a))
                        start = b
                for r0, r1 in runs:
                    self.canvas.create_rectangle(x0, r0 * ch, x0 + cw, (r1 + 1) * ch,
                                                 outline="#ffffff", width=2, tags="ov")
                ymid = (rows[0] + rows[-1] + 1) / 2 * ch
                self.canvas.create_text(x0 + cw + 4, ymid, text=note_name(midi), anchor="w",
                                        fill="#ffffff", font=("Segoe UI", 9, "bold"), tags="ov")
        x = self.son.scan_position * self.canvas_w
        self.canvas.create_line(x, 0, x, self.canvas_h, fill="#f43f5e", width=2, tags="ov")

    def _draw_legend(self):
        c, w = self.legend, self.canvas_w
        c.delete("all")
        mapper = self.son.mapper
        n = 240
        hues = np.linspace(240, 0, n)                     # mavi -> kırmızı
        bw = w / n
        last = None
        for i, h in enumerate(hues):
            rgb = self._hue_rgb(h)
            c.create_rectangle(i * bw, 0, (i + 1) * bw + 1, 14, outline="", fill=rgb)
            m = mapper.note_for_rgb(*[int(rgb[k:k + 2], 16) for k in (1, 3, 5)])
            if m is not None and m != last and m % 12 == mapper.scale.root:
                c.create_line(i * bw, 14, i * bw, 19, fill=FG)
                c.create_text(i * bw + 2, 26, text=note_name(m), anchor="w", fill=FG, font=("Segoe UI", 7))
            last = m
        c.create_text(2, 7, text="PES", anchor="w", fill="white", font=("Segoe UI", 7, "bold"))
        c.create_text(w - 2, 7, text="TİZ", anchor="e", fill="white", font=("Segoe UI", 7, "bold"))

    @staticmethod
    def _hue_rgb(h):
        import colorsys
        r, g, b = colorsys.hsv_to_rgb(h / 360.0, 1.0, 1.0)
        return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"

    def _draw_eq_curve(self):
        c = self.eq_canvas
        W, H = int(c["width"]), int(c["height"])
        c.delete("all")
        f = np.geomspace(20, 20000, 160)
        db = self.son.equalizer.frequency_response(f)
        def y(v): return H / 2 - v / 15.0 * (H / 2 - 10)
        for v in (-12, -6, 0, 6, 12):
            c.create_line(0, y(v), W, y(v), fill="#1e293b" if v else "#334155")
            c.create_text(3, y(v), text=f"{v:+d}", anchor="w", fill="#475569", font=("Segoe UI", 7))
        for fr in (100, 1000, 10000):
            x = np.log10(fr / 20) / np.log10(1000) * W
            c.create_line(x, 0, x, H, fill="#1e293b")
            c.create_text(x + 2, H - 8, text=f"{fr // 1000}k" if fr >= 1000 else str(fr),
                          anchor="w", fill="#475569", font=("Segoe UI", 7))
        pts = []
        for fi, d in zip(f, db):
            pts += [np.log10(fi / 20) / np.log10(1000) * W, y(d)]
        c.create_line(*pts, fill=ACCENT, width=2, smooth=True)

    def _draw_spectrum(self):
        c = self.spec_canvas
        W, H = int(c["width"]), int(c["height"])
        c.delete("all")
        bars = self.son.engine.spectrum
        n = len(bars)
        bw = W / n
        for i, v in enumerate(bars):
            h = v * (H - 14)
            col = "#38bdf8" if i < n * 0.3 else ("#34d399" if i < n * 0.7 else "#f472b6")
            c.create_rectangle(i * bw + 1, H - 12 - h, (i + 1) * bw - 1, H - 12, outline="", fill=col)
        for lbl, frac in (("Bas", 0.05), ("Mid", 0.45), ("Tiz", 0.88)):
            c.create_text(frac * W, H - 5, text=lbl, fill="#475569", font=("Segoe UI", 7))

    # ================================================================== döngü
    def _tick(self):
        data = self.son.map
        v = self.son.viewport
        key = (v.as_tuple(), id(data), self.show_grid.get(), id(self.son.grid))
        if key != self._drawn_view:
            self._drawn_view = key
            self._draw_map()
        self._draw_overlay()
        self._draw_spectrum()
        self._update_play_btn()

        if data is not None:
            b = v.to_lonlat(data.bounds)
            box = data.pixel_box(*v.as_tuple())
            g = self.son.grid
            per_cell = ""
            if g is not None:
                pw, ph = (box[2] - box[0]) / g.cols, (box[3] - box[1]) / g.rows
                per_cell = (f"  ·  hücre başına ≈ {pw:.1f}x{ph:.1f} piksel" if pw >= 1 and ph >= 1
                            else "  ·  hücre < 1 piksel: piksel piksel tarama")
            self.view_lbl.config(
                text=f"Görünüm: {v.zoom_level:.1f}x yakınlaştırma  ·  boylam {b.west:.1f}°…{b.east:.1f}°  "
                     f"enlem {b.south:.1f}°…{b.north:.1f}°  ·  {box[2] - box[0]}x{box[3] - box[1]} piksel{per_cell}")

        step = self.son.last_step
        if self.son.is_playing and step is not None:
            names = "  ".join(note_name(m) for m in sorted(step.sounding)) or "— sessiz (siyah / renksiz / ölçüm yok) —"
            self.notes_lbl.config(text=f"♪ {names}")
            s = step.stats
            self.filter_lbl.config(
                text=f"Sütun {step.column + 1}/{step.cols}:  {s.cells} sesli hücre → {s.unique} farklı nota "
                     f"({s.vertical_merged} dikey tekrar elendi)  ·  {s.held} nota devam ediyor (yeniden çalınmadı)  "
                     f"·  {s.started} yeni  ·  {s.stopped} sustu  ·  ses: {self.son.engine.active_voices}")
        elif not self.son.is_playing:
            self.notes_lbl.config(text="⏸ Durduruldu — ▶ Çal'a basın")
            self.filter_lbl.config(text="")
        self.root.after(40, self._tick)

    def close(self):
        self.son.close()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = WorldSoundTestApp(root)
    root.protocol("WM_DELETE_WINDOW", app.close)
    root.mainloop()
