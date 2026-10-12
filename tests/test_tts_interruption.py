import threading

from app.voice.text_to_speech import _write_cancellable


def test_pcm_writer_stops_before_the_next_frame_after_interruption() -> None:
    cancel = threading.Event()

    class Output:
        def __init__(self) -> None:
            self.writes = []

        def write(self, data: bytes) -> None:
            self.writes.append(data)
            cancel.set()

    output = Output()
    completed = _write_cancellable(output, b"x" * 3_000, cancel)

    assert completed is False
    assert len(output.writes) == 1
    assert len(output.writes[0]) == 960
