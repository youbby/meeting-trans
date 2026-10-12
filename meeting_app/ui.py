from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

from . import __version__
from .audio import list_devices
from .engine import Engine, EngineConfig
from .export import export_session
from .models import ModelPaths, local_path
from .paths import data_root, default_models
from .session import Session, Segment, SOURCES, atomic_text, timestamp


class App(tk.Tk):
    def __init__(self, demo=False):
        super().__init__()
        self.title("로컬 회의 기록 · Standalone Meeting Transcriber")
        width = min(1220, self.winfo_screenwidth() - 60)
        height = min(820, self.winfo_screenheight() - 110)
        self.geometry(f"{width}x{height}")
        self.minsize(min(1060, width), min(640, height))
        self.configure(bg="#eef3f8")
        self.events = queue.Queue()
        self.engine: Engine | None = None
        self.session = Session()
        self.session_path = None
        self.exporting = False
        self._export_pending = False
        self.export_paths = None
        self.paused = False
        self._last_revision = -1
        self._saved_revision = -1
        self._closing = False
        self.settings_path = data_root() / "settings.json"
        try:
            self.settings = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.settings = {}
        self.model_path = tk.StringVar(value=self.settings.get("models", str(default_models())))
        self.output_path = tk.StringVar(value=self.settings.get("output", str(data_root() / "sessions")))
        self.meeting_title = tk.StringVar(value="회의 기록")
        self.mic_on, self.system_on = tk.BooleanVar(value=True), tk.BooleanVar(value=True)
        self.aec_on, self.audio_on = tk.BooleanVar(value=True), tk.BooleanVar(value=False)
        self.auto_scroll = tk.BooleanVar(value=True)
        self.language = tk.StringVar(value="한국어")
        self.delay_ms = tk.IntVar(value=int(self.settings.get("echo_delay", 60)))
        self.threshold = tk.DoubleVar(value=float(self.settings.get("speaker_threshold", .62)))
        self.status = tk.StringVar(value="시작을 누르면 선택한 입력의 기록을 시작합니다.")
        self.capture_status = tk.StringVar(value="수집 대기 · 마이크와 PC 출력의 장치를 확인해 주세요.")
        self.lag = tk.StringVar(value="대기 구간 0 · 전사 지연 0초")
        self._style()
        self._build()
        self.refresh_devices()
        if demo:
            self._demo()
        self.protocol("WM_DELETE_WINDOW", self.close_app)
        self.after(100, self.poll)
        self.after(2000, self.autosave)

    def _style(self):
        self.option_add("*Font", ("맑은 고딕", 10))
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#eef3f8")
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("TLabel", background="#eef3f8", foreground="#26364c")
        style.configure("Card.TLabel", background="#ffffff", foreground="#26364c")
        style.configure("Muted.TLabel", foreground="#617087", background="#eef3f8")
        style.configure("TButton", padding=(12, 7), background="#ffffff", borderwidth=1)
        style.configure("Accent.TButton", background="#147c76", foreground="white", padding=(18, 9))
        style.map("Accent.TButton", background=[("active", "#0f655f"), ("disabled", "#9fb4b8")])
        style.configure("TCheckbutton", background="#ffffff", foreground="#26364c")
        style.configure("Treeview", rowheight=32, font=("맑은 고딕", 10), background="white", fieldbackground="white", borderwidth=0)
        style.configure("Treeview.Heading", font=("맑은 고딕", 10, "bold"), padding=7, background="#dfe8f1")
        style.map("Treeview", background=[("selected", "#d5eee9")], foreground=[("selected", "#173b37")])
        style.configure("Horizontal.TProgressbar", background="#168b82", troughcolor="#e2e9f0", borderwidth=0)

    def _build(self):
        header = tk.Frame(self, bg="#17283f", padx=24, pady=17)
        header.pack(fill="x")
        tk.Label(header, text="로컬 회의 기록", bg="#17283f", fg="white", font=("맑은 고딕", 21, "bold")).pack(side="left")
        tk.Label(header, text=f"v{__version__}  ·  음성 처리와 문서 저장은 PC 내부에서", bg="#17283f", fg="#b8d4df").pack(side="right")
        main = ttk.Frame(self, padding=(20, 15))
        main.pack(fill="both", expand=True)
        title_row = ttk.Frame(main)
        title_row.pack(fill="x", pady=(0, 12))
        ttk.Label(title_row, text="회의 제목").pack(side="left", padx=(0, 10))
        self.title_entry = ttk.Entry(title_row, textvariable=self.meeting_title, width=34)
        self.title_entry.pack(side="left")
        self.start_button = ttk.Button(title_row, text="● 기록 시작", command=self.start_session, style="Accent.TButton")
        self.start_button.pack(side="left", padx=(18, 6))
        self.pause_button = ttk.Button(title_row, text="일시정지", command=self.toggle_pause, state="disabled")
        self.pause_button.pack(side="left", padx=3)
        self.stop_button = ttk.Button(title_row, text="종료 및 저장", command=self.stop_session, state="disabled")
        self.stop_button.pack(side="left", padx=3)
        self.open_button = ttk.Button(title_row, text="세션 열기", command=self.open_session)
        self.open_button.pack(side="right")
        inputs = ttk.Frame(main)
        inputs.pack(fill="x")
        inputs.columnconfigure(0, weight=1)
        inputs.columnconfigure(1, weight=1)
        for column, source, label, variable in [(0, "MIC", "마이크 · 현장 참석자", self.mic_on), (1, "SYSTEM", "PC 출력 · 회의 / 동영상", self.system_on)]:
            card = ttk.Frame(inputs, style="Card.TFrame", padding=13)
            card.grid(row=0, column=column, sticky="ew", padx=(0, 6) if column == 0 else (6, 0))
            ttk.Checkbutton(card, text=label, variable=variable, command=self.mode_changed).pack(anchor="w")
            combo = ttk.Combobox(card, state="readonly")
            combo.pack(fill="x", pady=(8, 7))
            meter = ttk.Progressbar(card, maximum=1)
            meter.pack(fill="x")
            if source == "MIC":
                self.mic_combo, self.mic_meter = combo, meter
            else:
                self.output_combo, self.output_meter = combo, meter
        option_row = ttk.Frame(main, style="Card.TFrame", padding=(12, 9))
        option_row.pack(fill="x", pady=(8, 0))
        self.aec_check = ttk.Checkbutton(option_row, text="스피커 재수음 제외(AEC)", variable=self.aec_on)
        self.aec_check.pack(side="left")
        self.audio_check = ttk.Checkbutton(option_row, text="처리된 오디오도 로컬 보존", variable=self.audio_on)
        self.audio_check.pack(side="left", padx=16)
        self.lang_combo = ttk.Combobox(option_row, values=["한국어", "자동 감지", "영어"], textvariable=self.language, state="readonly", width=10)
        self.lang_combo.pack(side="left")
        self.refresh_button = ttk.Button(option_row, text="장치 새로고침", command=self.refresh_devices)
        self.refresh_button.pack(side="right")
        ttk.Label(main, textvariable=self.capture_status, style="Muted.TLabel").pack(anchor="w", pady=(8, 8))

        footer = ttk.Frame(main)
        footer.pack(side="bottom", fill="x", pady=(12, 0))
        panes = ttk.Panedwindow(main, orient="horizontal")
        panes.pack(fill="both", expand=True)
        transcript_frame = ttk.Frame(panes)
        speaker_frame = ttk.Frame(panes, width=260)
        panes.add(transcript_frame, weight=4)
        panes.add(speaker_frame, weight=1)
        transcript_top = ttk.Frame(transcript_frame)
        transcript_top.pack(fill="x", pady=(0, 6))
        ttk.Label(transcript_top, text="실시간 전사", font=("맑은 고딕", 12, "bold")).pack(side="left")
        ttk.Checkbutton(transcript_top, text="자동 스크롤", variable=self.auto_scroll).pack(side="right")
        transcript_tools = ttk.Frame(transcript_frame)
        transcript_tools.pack(side="bottom", fill="x")
        self.detail = tk.Text(transcript_tools, height=3, wrap="word", font=("맑은 고딕", 10),
            padx=8, pady=6, relief="flat", bg="#f5f8fc", fg="#34445b", state="disabled")
        self.detail.pack(fill="x", pady=(6, 4))
        ttk.Button(transcript_tools, text="선택한 발언 수정 / 발화자 변경", command=self.edit_segment).pack(anchor="w")
        tree_frame = ttk.Frame(transcript_frame)
        tree_frame.pack(fill="both", expand=True)
        self.transcript = ttk.Treeview(tree_frame, columns=("time", "source", "speaker", "text", "state"), show="headings", selectmode="browse", height=6)
        for name, title, width in [("time", "시간", 72), ("source", "입력", 78), ("speaker", "발화자", 100), ("text", "내용", 375), ("state", "상태", 100)]:
            self.transcript.heading(name, text=title)
            self.transcript.column(name, width=width, minwidth=60, stretch=name == "text")
        self.transcript.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.transcript.yview)
        scrollbar.pack(side="right", fill="y")
        self.transcript.configure(yscrollcommand=scrollbar.set)
        self.transcript.bind("<Double-1>", lambda event: self.edit_segment())
        self.transcript.bind("<<TreeviewSelect>>", lambda event: self.show_detail())
        self.transcript.tag_configure("pending", foreground="#8993a1")
        self.transcript.tag_configure("system", background="#f4f9ff")
        ttk.Label(speaker_frame, text="발화자", font=("맑은 고딕", 12, "bold")).pack(anchor="w", pady=(0, 7), padx=8)
        speaker_tools = ttk.Frame(speaker_frame)
        speaker_tools.pack(side="bottom", fill="x")
        ttk.Button(speaker_tools, text="이름 변경", command=self.rename_speaker).pack(anchor="w", padx=8, pady=(7, 0))
        self.speaker_tree = ttk.Treeview(speaker_frame, columns=("name", "source"), show="headings", selectmode="browse", height=6)
        self.speaker_tree.heading("name", text="이름")
        self.speaker_tree.heading("source", text="수집 출처")
        self.speaker_tree.column("name", width=120)
        self.speaker_tree.column("source", width=95)
        self.speaker_tree.pack(fill="both", expand=True, padx=(8, 0))
        self.speaker_tree.bind("<Double-1>", lambda event: self.rename_speaker())

        bottom = ttk.Frame(footer)
        bottom.pack(fill="x")
        self.save_button = ttk.Button(bottom, text="MD 저장 + PDF 생성", command=self.save_export)
        self.save_button.pack(side="left")
        ttk.Button(bottom, text="저장 폴더", command=self.open_folder).pack(side="left", padx=6)
        self.settings_button = ttk.Button(bottom, text="설정 / 모델 경로", command=self.show_settings)
        self.settings_button.pack(side="left")
        ttk.Label(bottom, textvariable=self.lag, style="Muted.TLabel").pack(side="right")
        ttk.Label(footer, textvariable=self.status, wraplength=1120).pack(anchor="w", pady=(10, 0))
        ttk.Label(footer, text="발화자 분류는 수정할 수 있습니다. 회의 앱 음소거와 이 프로그램의 마이크 수집은 별개입니다.", style="Muted.TLabel").pack(anchor="w", pady=(4, 0))

    def emit(self, kind, value):
        self.events.put((kind, value))

    def refresh_devices(self):
        try:
            self.mics, self.outputs = list_devices()
            for combo, devices, saved in [(self.mic_combo, self.mics, self.settings.get("microphone")), (self.output_combo, self.outputs, self.settings.get("output_device"))]:
                labels = [d.name for d in devices]
                combo.configure(values=labels)
                if labels:
                    combo.current(labels.index(saved) if saved in labels else 0)
                else:
                    combo.set("사용 가능한 WASAPI 장치 없음")
        except Exception as exc:
            self.mics, self.outputs = [], []
            self.status.set(f"장치 확인 실패: {exc}")

    def _running(self):
        return self.engine is not None and self.engine.thread is not None and self.engine.thread.is_alive()

    def start_session(self):
        if self._running() or self.exporting:
            return
        try:
            if not (self.mic_on.get() or self.system_on.get()):
                raise ValueError("마이크 또는 PC 출력 중 하나 이상을 선택해 주세요.")
            model_root = local_path(self.model_path.get())
            ModelPaths.resolve(model_root)
            mic = self.mics[self.mic_combo.current()] if self.mics and self.mic_combo.current() >= 0 else None
            output = self.outputs[self.output_combo.current()] if self.outputs and self.output_combo.current() >= 0 else None
            if self.mic_on.get() and mic is None:
                raise ValueError("사용할 마이크가 없습니다.")
            if (self.system_on.get() or (self.mic_on.get() and self.aec_on.get())) and output is None:
                raise ValueError("PC 출력 또는 에코 제거용 출력 장치가 없습니다.")
            session = Session(self.meeting_title.get())
            folder = local_path(self.output_path.get()) / f"{datetime.now():%Y%m%d_%H%M%S}_{session.id[:8]}"
            folder.mkdir(parents=True, exist_ok=False)
            self.session, self.session_path = session, folder / "session.json"
            config = EngineConfig(model_root, folder, mic, output, self.mic_on.get(), self.system_on.get(),
                self.aec_on.get(), self.audio_on.get(), {"한국어": "ko", "영어": "en", "자동 감지": ""}[self.language.get()],
                echo_delay_ms=self.delay_ms.get(), speaker_threshold=self.threshold.get())
            self.engine = Engine(session, config, self.emit)
            self.paused = False
            self._last_revision = -1
            self.set_busy(True)
            self.status.set("모델 준비 중 · 아직 오디오를 수집하지 않습니다.")
            self.save_settings()
            self.engine.start()
        except Exception as exc:
            messagebox.showerror("시작할 수 없습니다", str(exc), parent=self)

    def set_busy(self, busy):
        for widget in (self.start_button, self.open_button, self.refresh_button, self.settings_button, self.title_entry, self.aec_check, self.audio_check):
            widget.configure(state="disabled" if busy else "normal")
        for combo in (self.mic_combo, self.output_combo, self.lang_combo):
            combo.configure(state="disabled" if busy else "readonly")
        self.pause_button.configure(state="normal" if busy else "disabled")
        self.stop_button.configure(state="normal" if busy else "disabled")

    def mode_changed(self):
        if self._running():
            self.engine.set_modes(self.mic_on.get(), self.system_on.get(), self.paused)

    def toggle_pause(self):
        if self._running():
            self.paused = not self.paused
            self.pause_button.configure(text="계속 기록" if self.paused else "일시정지")
            self.mode_changed()

    def stop_session(self):
        if self._running():
            self.engine.stop()
            self.stop_button.configure(state="disabled")
            self.pause_button.configure(state="disabled")
            self.status.set("수집 종료 · 남은 전사와 발화자 분석을 완료하고 저장합니다.")

    def refresh_session(self):
        data = self.session.snapshot()
        if data["revision"] == self._last_revision:
            return
        self._last_revision = data["revision"]
        selected = self.transcript.selection()
        scroll = self.transcript.yview()
        speaker_selected = self.speaker_tree.selection()
        self.transcript.delete(*self.transcript.get_children())
        self.speaker_tree.delete(*self.speaker_tree.get_children())
        names = {}
        for speaker in data["speakers"]:
            names[speaker["id"]] = speaker["name"]
            self.speaker_tree.insert("", "end", iid=speaker["id"], values=(speaker["name"], f"{SOURCES[speaker['source']]} ({speaker['source']})"))
        for segment in data["segments"]:
            tag = "pending" if not segment["speaker_id"] else ("system" if segment["source"] == "SYSTEM" else "mic")
            self.transcript.insert("", "end", iid=segment["id"], values=(timestamp(segment["start"]), SOURCES[segment["source"]],
                names.get(segment["speaker_id"], "확인 중"), segment["text"], segment["status"]), tags=(tag,))
        if selected and self.transcript.exists(selected[0]):
            self.transcript.selection_set(selected[0])
        if speaker_selected and self.speaker_tree.exists(speaker_selected[0]):
            self.speaker_tree.selection_set(speaker_selected[0])
        if self.auto_scroll.get() and data["segments"]:
            self.transcript.see(data["segments"][-1]["id"])
        elif scroll:
            self.transcript.yview_moveto(scroll[0])

    def rename_speaker(self):
        selected = self.speaker_tree.selection()
        if not selected:
            self.status.set("이름을 변경할 발화자를 선택해 주세요.")
            return
        sid = selected[0]
        name = simpledialog.askstring("발화자 이름", "표시할 이름", initialvalue=self.session.speakers[sid].name, parent=self)
        if name is not None:
            try:
                self.session.rename(sid, name)
                self.refresh_session()
                self.status.set("이름을 변경했습니다. 기존 MD·PDF는 저장 버튼으로 다시 생성할 수 있습니다.")
            except ValueError as exc:
                messagebox.showerror("이름 확인", str(exc), parent=self)

    def show_detail(self):
        selected = self.transcript.selection()
        if not selected or selected[0] not in self.session.segments:
            return
        segment = self.session.segments[selected[0]]
        speaker = self.session.speakers.get(segment.speaker_id)
        name = speaker.name if speaker else "발화자 미확정"
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", f"{timestamp(segment.start)} · {name} · {SOURCES[segment.source]} ({segment.source})\n{segment.text}")
        self.detail.configure(state="disabled")

    def edit_segment(self):
        selected = self.transcript.selection()
        if not selected or selected[0] not in self.session.segments:
            return
        segment = self.session.segments[selected[0]]
        dialog = tk.Toplevel(self)
        dialog.title("발언 수정")
        dialog.geometry("620x340")
        dialog.transient(self)
        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=f"{timestamp(segment.start)} · {SOURCES[segment.source]} ({segment.source})").pack(anchor="w")
        choices = [(None, "발화자 미지정")] + [(s.id, f"{s.name} · {s.source}") for s in self.session.speakers.values() if s.source == segment.source]
        combo = ttk.Combobox(frame, values=[name for _, name in choices], state="readonly")
        combo.pack(fill="x", pady=10)
        combo.current(next((i for i, (sid, _) in enumerate(choices) if sid == segment.speaker_id), 0))
        text = tk.Text(frame, height=7, wrap="word", font=("맑은 고딕", 11), padx=8, pady=8)
        text.insert("1.0", segment.text)
        text.pack(fill="both", expand=True)

        def apply():
            try:
                self.session.edit_segment(segment.id, text.get("1.0", "end-1c"), choices[combo.current()][0])
                self.refresh_session()
                dialog.destroy()
            except (ValueError, KeyError) as exc:
                messagebox.showerror("수정 실패", str(exc), parent=dialog)
        ttk.Button(frame, text="수정 적용", command=apply).pack(anchor="e", pady=(12, 0))

    def save_export(self):
        if self.exporting:
            self._export_pending = True
            return
        snapshot = self.session.snapshot()
        try:
            folder = self.session_path.parent if self.session_path else local_path(self.output_path.get()) / self.session.id[:8]
            folder.mkdir(parents=True, exist_ok=True)
            self.session_path = folder / "session.json"
        except Exception as exc:
            messagebox.showerror("저장 경로 오류", str(exc), parent=self)
            return
        self.exporting = True
        self.save_button.configure(state="disabled")
        self.open_button.configure(state="disabled")
        self.status.set("Markdown 저장 및 PDF 생성 중…")
        session, session_path = self.session, self.session_path

        def worker():
            try:
                session.save(session_path)
                result = export_session(snapshot, folder)
                self.emit("export", (result, snapshot["revision"]))
            except Exception as exc:
                self.emit("export_error", str(exc))
        threading.Thread(target=worker, name="document-export", daemon=False).start()

    def open_session(self):
        if self.exporting or self._running():
            return
        path = filedialog.askopenfilename(parent=self, title="세션 열기", filetypes=[("회의 세션", "*.json")], initialdir=self.output_path.get())
        if not path:
            return
        try:
            self.session_path = local_path(path)
            self.session = Session.load(self.session_path)
            self.meeting_title.set(self.session.title)
            self._last_revision = -1
            self.refresh_session()
            self.status.set("세션을 열었습니다. 이름과 발언을 수정하고 문서를 다시 저장할 수 있습니다.")
        except Exception as exc:
            messagebox.showerror("세션 열기 실패", str(exc), parent=self)

    def open_folder(self):
        try:
            folder = self.session_path.parent if self.session_path else local_path(self.output_path.get())
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(str(folder))
        except Exception as exc:
            messagebox.showerror("폴더 열기 실패", str(exc), parent=self)

    def show_settings(self):
        dialog = tk.Toplevel(self)
        dialog.title("로컬 설정")
        dialog.geometry("760x360")
        dialog.transient(self)
        body = ttk.Frame(dialog, padding=20)
        body.pack(fill="both", expand=True)
        for label, var in [("모델 폴더", self.model_path), ("저장 폴더", self.output_path)]:
            ttk.Label(body, text=label).pack(anchor="w")
            row = ttk.Frame(body)
            row.pack(fill="x", pady=(5, 12))
            ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)
            def browse(variable=var):
                chosen = filedialog.askdirectory(parent=dialog, initialdir=variable.get())
                if chosen:
                    variable.set(chosen)
            ttk.Button(row, text="선택", command=browse).pack(side="right", padx=(8, 0))
        row = ttk.Frame(body)
        row.pack(fill="x", pady=8)
        ttk.Label(row, text="에코 지연(ms)").pack(side="left")
        ttk.Spinbox(row, from_=0, to=500, increment=10, textvariable=self.delay_ms, width=7).pack(side="left", padx=8)
        ttk.Label(row, text="발화자 유사도 기준").pack(side="left", padx=(15, 0))
        ttk.Spinbox(row, from_=.3, to=.9, increment=.02, textvariable=self.threshold, width=7).pack(side="left", padx=8)
        ttk.Label(body, text="모델은 별도 준비 도구로 다운로드합니다. 이 창에서는 외부에 접속하지 않습니다.\n유사도 기준이 높을수록 서로 다른 발화자가 더 많이 생길 수 있습니다.\n저장 위치는 자동 클라우드 동기화가 없는 로컬 폴더를 사용해 주세요.", wraplength=700, style="Muted.TLabel").pack(anchor="w", pady=12)

        def save():
            try:
                local_path(self.model_path.get())
                local_path(self.output_path.get())
                if not (0 <= self.delay_ms.get() <= 500 and .3 <= self.threshold.get() <= .9):
                    raise ValueError("설정 범위를 확인해 주세요.")
                self.save_settings()
                dialog.destroy()
            except Exception as exc:
                messagebox.showerror("설정 오류", str(exc), parent=dialog)
        ttk.Button(body, text="설정 저장", command=save).pack(anchor="e")

    def save_settings(self):
        settings = {"models": self.model_path.get(), "output": self.output_path.get(),
            "microphone": self.mic_combo.get(), "output_device": self.output_combo.get(),
            "echo_delay": self.delay_ms.get(), "speaker_threshold": self.threshold.get()}
        atomic_text(self.settings_path, json.dumps(settings, ensure_ascii=False, indent=2))

    def autosave(self):
        if self.session_path and self.session.revision != self._saved_revision:
            try:
                self.session.save(self.session_path)
                self._saved_revision = self.session.revision
            except Exception as exc:
                self.status.set(f"자동 저장 실패: {exc}")
        self.after(2000, self.autosave)

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind in {"status", "notice"}:
                    self.status.set(value)
                elif kind == "levels":
                    self.mic_meter["value"] = value["MIC"]
                    self.output_meter["value"] = value["SYSTEM"]
                elif kind == "capture":
                    self.capture_status.set(f"마이크 {'수집 중' if value['mic'] else '꺼짐'} · PC 출력 전사 {'켜짐' if value['system'] else '꺼짐'}" + (" · 에코 제거용 출력 참조 수집 중" if value["reference"] else ""))
                elif kind == "aec":
                    self.capture_status.set(value)
                elif kind == "lag":
                    self.lag.set(f"대기 구간 {value['queued']} · 전사 지연 {value['seconds']:.1f}초")
                elif kind == "error":
                    self.status.set(f"오류: {value}")
                    if not self._closing:
                        messagebox.showerror("처리 오류", value, parent=self)
                elif kind == "state" and value == "stopped":
                    self.set_busy(False)
                    self.pause_button.configure(text="일시정지")
                    self.capture_status.set("수집 종료 · 모든 입력이 꺼졌습니다.")
                    self.mic_meter["value"] = self.output_meter["value"] = 0
                    self.save_export()
                elif kind == "state" and value == "running":
                    self.status.set("기록 중 · 텍스트를 먼저 표시하고 발화자를 분석합니다.")
                elif kind in {"export", "export_error"}:
                    self.exporting = False
                    self.save_button.configure(state="normal")
                    self.open_button.configure(state="disabled" if self._running() else "normal")
                    if kind == "export":
                        (md, pdf, error), revision = value
                        self.export_paths = (md, pdf)
                        self.status.set(f"MD 저장 완료 · PDF {'생성 완료' if pdf else '실패: ' + str(error)} · {md.parent}" + (" · 추가 수정은 다시 저장해 주세요." if revision != self.session.revision else ""))
                    else:
                        self.status.set(f"문서 저장 실패: {value}")
                    if self._export_pending:
                        self._export_pending = False
                        self.save_export()
        except queue.Empty:
            pass
        self.refresh_session()
        if self._closing and not self._running() and not self.exporting:
            self.destroy()
            return
        self.after(100, self.poll)

    def close_app(self):
        if self._running():
            if not messagebox.askyesno("기록 종료", "기록을 종료하고 남은 처리와 저장이 끝나면 닫을까요?", parent=self):
                return
            self._closing = True
            self.stop_session()
        elif self.exporting:
            self._closing = True
            self.status.set("문서 저장이 끝나면 닫습니다.")
        else:
            if self.session_path:
                self.session.save(self.session_path)
            self.destroy()

    def _demo(self):
        self.session = Session("제품 개발 주간 회의 · 화면 예시")
        a, b, c = [self.session.add_speaker(source) for source in ("MIC", "MIC", "SYSTEM")]
        for sid, name in [(a, "현장 참석자 A"), (b, "김대리"), (c, "박팀장")]:
            self.session.rename(sid, name)
        samples = [(8, "MIC", a, "오늘은 개발 일정과 검증 결과를 확인하겠습니다."),
            (15, "MIC", b, "마이크와 PC 출력은 각각 켜고 끌 수 있습니다."),
            (24, "SYSTEM", c, "발화자 이름을 바꾸면 이전 발언에도 반영됩니다."),
            (32, "MIC", a, "회의가 끝나면 Markdown과 PDF로 저장하겠습니다.")]
        for i, (t, source, sid, text) in enumerate(samples):
            self.session.add_segment(Segment(f"demo{i}", t, t + 5, source, text, sid, "분류됨"))
        self.status.set("화면 예시 · 실제 마이크나 PC 오디오는 수집하지 않습니다.")
        self.meeting_title.set(self.session.title)
        self.refresh_session()
