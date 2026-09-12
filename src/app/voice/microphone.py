"""One persistent microphone stream shared by DARWIN's voice pipeline."""

import atexit
from collections import deque
import os
from pathlib import Path
from queue import Empty, Full, Queue
import subprocess
import sys
from threading import Lock, Thread
from typing import Protocol

import numpy as np
import sounddevice as sd


SAMPLE_RATE = 16_000
FRAME_SIZE = 1_280
MAX_BUFFERED_FRAMES = 125  # Ten seconds of audio at 80 ms per frame.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_APPLE_HELPER = (
    PROJECT_ROOT
    / "native"
    / "macos_voice_audio"
    / ".build"
    / "release"
    / "darwin-voice-capture"
)


class MicrophoneStream(Protocol):
    """Blocking stream contract shared by wake detection and command capture."""

    def start(self) -> None: ...

    def read(self, frames: int) -> tuple[np.ndarray, bool]: ...

    def clear(self) -> None: ...

    def suspend(self) -> None: ...

    def resume(self) -> None: ...

    def close(self) -> None: ...


class PersistentMicrophone:
    """Keep PortAudio open and expose blocking reads to voice consumers."""

    def __init__(self, stream_factory=sd.InputStream) -> None:
        self._frames: Queue[np.ndarray] = Queue(maxsize=MAX_BUFFERED_FRAMES)
        self._overflowed = False
        self._lock = Lock()
        self._closed = False
        self._stream = stream_factory(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=FRAME_SIZE,
            callback=self._receive_audio,
        )
        atexit.register(self.close)

    def _receive_audio(self, audio, _frame_count, _time_info, status) -> None:
        frame = np.asarray(audio, dtype=np.int16).copy()
        if status:
            with self._lock:
                self._overflowed = True

        try:
            self._frames.put_nowait(frame)
        except Full:
            # Keep the newest live audio rather than stale buffered audio.
            try:
                self._frames.get_nowait()
            except Empty:
                pass
            self._frames.put_nowait(frame)
            with self._lock:
                self._overflowed = True

    def start(self) -> None:
        if self._closed:
            raise RuntimeError("The microphone has already been closed.")
        if not self._stream.active:
            self._stream.start()

    def read(self, frames: int) -> tuple[np.ndarray, bool]:
        """Return one live frame using sounddevice's blocking-read contract."""
        if frames != FRAME_SIZE:
            raise ValueError(f"Persistent microphone reads must use {FRAME_SIZE} frames.")

        audio = self._frames.get()
        with self._lock:
            overflowed = self._overflowed
            self._overflowed = False
        return audio, overflowed

    def clear(self) -> None:
        """Discard buffered audio, including DARWIN's own synthesized speech."""
        while True:
            try:
                self._frames.get_nowait()
            except Empty:
                break

    def suspend(self) -> None:
        """Release PortAudio while DARWIN plays its response."""
        if self._stream.active:
            self._stream.stop()
        self.clear()

    def resume(self) -> None:
        self.start()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._stream.active:
            self._stream.stop()
        self._stream.close()


class AppleVoiceProcessedMicrophone:
    """Read AEC/NS/AGC-processed PCM from DARWIN's native macOS helper."""

    def __init__(
        self,
        helper_path: Path | None = None,
        process_factory=subprocess.Popen,
    ) -> None:
        configured = os.getenv("DARWIN_APPLE_AUDIO_HELPER")
        self.helper_path = helper_path or (
            Path(configured).expanduser() if configured else DEFAULT_APPLE_HELPER
        )
        self._process_factory = process_factory
        self._frames: Queue[np.ndarray] = Queue(maxsize=MAX_BUFFERED_FRAMES)
        self._overflowed = False
        self._lock = Lock()
        self._closed = False
        self._process = None
        self._reader: Thread | None = None
        self._stderr_reader: Thread | None = None
        self._diagnostics: deque[str] = deque(maxlen=20)
        atexit.register(self.close)

    @property
    def available(self) -> bool:
        return sys.platform == "darwin" and self.helper_path.is_file()

    def start(self) -> None:
        if self._closed:
            raise RuntimeError("The microphone has already been closed.")
        if self._process is not None:
            return
        if sys.platform != "darwin":
            raise RuntimeError("Apple voice-processed audio requires macOS.")
        if not self.helper_path.is_file():
            raise FileNotFoundError(
                "The Apple audio helper has not been built. Run: "
                "native/macos_voice_audio/build.sh"
            )

        self._process = self._process_factory(
            [str(self.helper_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        if self._process.stdout is None or self._process.stderr is None:
            self.close()
            raise RuntimeError("The Apple audio helper did not expose its audio pipes.")
        process = self._process
        self._reader = Thread(target=self._read_audio, args=(process,), daemon=True)
        self._stderr_reader = Thread(
            target=self._read_diagnostics,
            args=(process,),
            daemon=True,
        )
        self._reader.start()
        self._stderr_reader.start()

    def _read_audio(self, process) -> None:
        frame_bytes = FRAME_SIZE * np.dtype(np.int16).itemsize
        pending = bytearray()
        while not self._closed and process.poll() is None:
            chunk = process.stdout.read(frame_bytes - len(pending))
            if not chunk:
                break
            pending.extend(chunk)
            if len(pending) < frame_bytes:
                continue
            frame = np.frombuffer(pending, dtype="<i2").copy().reshape(-1, 1)
            pending.clear()
            self._enqueue(frame)

    def _read_diagnostics(self, process) -> None:
        while not self._closed and process.poll() is None:
            line = process.stderr.readline()
            if not line:
                break
            self._diagnostics.append(line.decode("utf-8", errors="replace").strip())

    def _enqueue(self, frame: np.ndarray) -> None:
        try:
            self._frames.put_nowait(frame)
        except Full:
            try:
                self._frames.get_nowait()
            except Empty:
                pass
            self._frames.put_nowait(frame)
            with self._lock:
                self._overflowed = True

    def read(self, frames: int) -> tuple[np.ndarray, bool]:
        if frames != FRAME_SIZE:
            raise ValueError(f"Persistent microphone reads must use {FRAME_SIZE} frames.")
        while True:
            try:
                audio = self._frames.get(timeout=0.25)
                break
            except Empty:
                if self._process is None:
                    raise RuntimeError("The Apple audio helper is not running.")
                return_code = self._process.poll()
                if return_code is not None:
                    detail = "; ".join(self._diagnostics) or "no diagnostic output"
                    raise RuntimeError(
                        f"Apple audio helper exited with code {return_code}: {detail}"
                    )
        with self._lock:
            overflowed = self._overflowed
            self._overflowed = False
        return audio, overflowed

    def clear(self) -> None:
        while True:
            try:
                self._frames.get_nowait()
            except Empty:
                break

    def suspend(self) -> None:
        """Stop VoiceProcessingIO so it cannot duck DARWIN's own TTS."""
        self._stop_process()
        self.clear()

    def resume(self) -> None:
        self.start()

    def _stop_process(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop_process()


def create_microphone(backend: str | None = None) -> MicrophoneStream:
    """Create the configured capture backend with a safe PortAudio fallback."""
    selected = (backend or os.getenv("DARWIN_MICROPHONE_BACKEND", "auto")).lower()
    if selected not in {"auto", "apple", "portaudio"}:
        raise ValueError(
            "DARWIN_MICROPHONE_BACKEND must be auto, apple, or portaudio."
        )

    if selected in {"auto", "apple"}:
        apple = AppleVoiceProcessedMicrophone()
        if apple.available:
            return apple
        if selected == "apple":
            raise FileNotFoundError(
                f"Apple audio helper is unavailable at {apple.helper_path}. "
                "Run native/macos_voice_audio/build.sh."
            )
    return PersistentMicrophone()
