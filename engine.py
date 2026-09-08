import random, threading, time
from pynput.keyboard import Controller, Key

class TypingEngine:
    def __init__(self, config):
        self.config = config
        self._ctrl = Controller()
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._thread = None
        self.on_progress = None
        self.on_status = None
        self.on_done = None

    def start(self, text, countdown=None):
        if self._thread and self._thread.is_alive(): return
        cd = countdown if countdown is not None else self.config.countdown
        self._stop_event.clear()
        self._pause_event.set()
        self._thread = threading.Thread(target=self._run, args=(text, cd), daemon=True)
        self._thread.start()

    def pause(self):  self._pause_event.clear()
    def resume(self): self._pause_event.set()
    def stop(self):
        self._stop_event.set()
        self._pause_event.set()

    def _run(self, text, countdown):
        for i in range(int(countdown), 0, -1):
            if self._stop_event.is_set():
                if self.on_done: self.on_done()
                return
            if self.on_status: self.on_status(f"Starting in {i}...")
            time.sleep(1)
        if self._stop_event.is_set():
            if self.on_done: self.on_done()
            return
        if self.on_status: self.on_status("Typing...")

        total = len(text)
        i = 0
        burst_counter = 0

        while i < total:
            if self._stop_event.is_set(): break
            self._pause_event.wait()
            if self._stop_event.is_set(): break

            for stroke in self._maybe_typo(text[i]):
                if self._stop_event.is_set(): break
                if stroke == "\b":
                    time.sleep(self.config.error_correction_delay * 0.5)
                    self._ctrl.press(Key.backspace)
                    self._ctrl.release(Key.backspace)
                    time.sleep(self.config.error_correction_delay * 0.5)
                else:
                    self._send_char(stroke)

            i += 1
            burst_counter += 1
            if self.on_progress: self.on_progress(i, total)

            if self.config.burst_mode and burst_counter >= self.config.burst_chars:
                burst_counter = 0
                time.sleep(self.config.burst_pause)
                continue
            if random.random() < self.config.thinking_pause_chance:
                time.sleep(random.uniform(self.config.thinking_pause_min, self.config.thinking_pause_max))
                continue
            time.sleep(self._human_delay())

        if self.on_done: self.on_done()

    def _send_char(self, char):
        # Explicit key handling - more reliable than controller.type()
        if char == "\n":
            self._ctrl.press(Key.enter); self._ctrl.release(Key.enter); return
        if char == "\t":
            self._ctrl.press(Key.tab); self._ctrl.release(Key.tab); return
        if char == " ":
            # Fix: use Key.space explicitly (controller.type(" ") fails in some apps)
            self._ctrl.press(Key.space); self._ctrl.release(Key.space); return

        if self.config.unicode_method == "clipboard" or ord(char) > 0xFFFF:
            self._send_via_clipboard(char)
        else:
            try:
                self._ctrl.type(char)
            except Exception:
                self._send_via_clipboard(char)

    def _send_via_clipboard(self, char):
        try:
            import pyperclip
            old = pyperclip.paste()
            pyperclip.copy(char)
            time.sleep(0.025)
            self._ctrl.press(Key.ctrl); self._ctrl.press("v")
            self._ctrl.release("v"); self._ctrl.release(Key.ctrl)
            time.sleep(0.06)
            try: pyperclip.copy(old)
            except: pass
        except Exception:
            try: self._ctrl.type(char)
            except: pass

    def _human_delay(self):
        base = 60.0 / (max(1, self.config.wpm) * 5)
        jitter = base * random.uniform(-self.config.variation, self.config.variation)
        return max(0.015, base + jitter)

    def _maybe_typo(self, char):
        if char in (" ", "\n", "\t", "\r"): return [char]
        if random.random() < self.config.error_rate:
            return [random.choice("abcdefghijklmnopqrstuvwxyz"), "\b", char]
        return [char]
