#!/usr/bin/env python3
"""Record keyword-spotting training data through the wearable's own microphone.

    python tools/record_dataset.py --speaker S01            # keywords + filler words
    python tools/record_dataset.py --speaker S01 --noise 120 # also 2 min of background

Why the device's microphone and not a laptop's: a model trained on one
microphone and run on another loses accuracy, and the INMP441 behind a
plastic case does not sound like a laptop. Record through the hardware the
model will run on.

Output: dataset/<label>/<label>.<speaker>_<n>.wav, 16 kHz mono 16-bit, one
second each. Edge Impulse's uploader takes the label from the text before the
first dot, so the folder uploads as is:

    edge-impulse-uploader --category split dataset/*/*.wav

Speakers are identified only by a code you choose (S01, S02 ...). Keep the
code-to-name list, and the signed consent forms, off this computer's dataset
folder.
"""

import argparse
import csv
import random
import struct
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np
import serial
import serial.tools.list_ports

HERE = Path(__file__).resolve().parent
FIRMWARE = HERE.parent
RATE = 16000
CAPTURE_S = 1.5
SYNC = b"\xA5\x5A"

# Ordinary words for the "_unknown" class. Without them the model learns that
# any speech at all is a command. The near-misses (থাকো/থামো, আবার/আবার বলো)
# are the ones that matter most.
FILLER = [
    "আম", "পানি", "কলম", "বাজার", "চা", "বই", "মোবাইল", "ভাত", "জামা", "চাবি",
    "থাকো", "আবার", "সামনে যাও", "জানালা", "ব্যাগ",
    "apple", "water", "pen", "phone", "hello", "yes", "no", "okay", "thanks", "listen",
]


class Stream:
    """Reads the device's framed 16 kHz stream on a background thread."""

    def __init__(self, port):
        self.ser = serial.Serial(port, 115200, timeout=0.2)
        self.buf = bytearray()
        self.samples = []
        self.lock = threading.Lock()
        self.running = True
        self.ser.reset_input_buffer()
        self.ser.write(b"stop\n")
        time.sleep(0.3)
        self.ser.reset_input_buffer()
        self.ser.write(b"rec\n")
        self._await_banner()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _await_banner(self):
        deadline = time.time() + 3.0
        seen = bytearray()
        while time.time() < deadline:
            seen += self.ser.read(64)
            i = seen.find(b"REC ")
            if i >= 0:
                j = seen.find(b"\n", i)
                if j >= 0:
                    self.buf += seen[j + 1:]
                    return
        sys.exit("The device did not start streaming. Is the firmware flashed, and is this the right port?")

    def _run(self):
        while self.running:
            self.buf += self.ser.read(4096)
            while True:
                i = self.buf.find(SYNC)
                if i < 0:
                    del self.buf[:-1]
                    break
                if len(self.buf) < i + 4:
                    del self.buf[:i]
                    break
                (n,) = struct.unpack_from("<H", self.buf, i + 2)
                if n == 0 or n > 4096:
                    del self.buf[: i + 2]
                    continue
                end = i + 4 + 2 * n
                if len(self.buf) < end:
                    del self.buf[:i]
                    break
                block = np.frombuffer(bytes(self.buf[i + 4:end]), dtype="<i2")
                with self.lock:
                    self.samples.append(block)
                del self.buf[:end]

    def clear(self):
        with self.lock:
            self.samples = []

    def take(self, seconds):
        need = int(seconds * RATE)
        while True:
            with self.lock:
                have = sum(len(b) for b in self.samples)
                if have >= need:
                    data = np.concatenate(self.samples)
                    self.samples = []
                    return data[:need]
            time.sleep(0.02)

    def close(self):
        self.running = False
        self.thread.join(timeout=1.0)
        self.ser.write(b"stop\n")
        self.ser.close()


def find_port():
    ports = [p for p in serial.tools.list_ports.comports() if p.vid == 0x0483]
    if len(ports) == 1:
        return ports[0].device
    names = ", ".join(p.device for p in serial.tools.list_ports.comports()) or "none"
    sys.exit(f"Could not pick the device automatically (serial ports: {names}). Pass --port COMx.")


def loudest_second(x):
    win = RATE
    best, best_e = 0, -1.0
    for start in range(0, len(x) - win + 1, RATE // 20):
        e = float(np.sum(x[start:start + win].astype(np.float64) ** 2))
        if e > best_e:
            best, best_e = start, e
    return x[best:best + win]


def dbfs(x):
    peak = int(np.max(np.abs(x.astype(np.int32)))) if len(x) else 0
    return -96.0 if peak == 0 else 20 * np.log10(peak / 32768.0)


def save(path, x):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(x.astype("<i2").tobytes())


def record_word(stream, out_dir, label, prompt, speaker, n):
    path = out_dir / label / f"{label}.{speaker}_{n:02d}.wav"
    if path.exists():
        return
    while True:
        print(f"\n  Say:  {prompt}")
        time.sleep(0.4)
        stream.clear()
        print("  ... now")
        clip = loudest_second(stream.take(CAPTURE_S))
        level = dbfs(clip)
        if level < -40:
            print(f"  too quiet ({level:.0f} dBFS) - again, a little louder")
            continue
        if level > -0.5:
            print("  clipped - again, a little further from the device")
            continue
        save(path, clip)
        print(f"  saved {path.name} ({level:.0f} dBFS)")
        return


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--speaker", required=True, help="anonymous speaker code, e.g. S01")
    ap.add_argument("--port", help="serial port (found automatically if only one STM32 is connected)")
    ap.add_argument("--reps", type=int, default=10, help="repetitions of each keyword")
    ap.add_argument("--noise", type=int, default=0, help="seconds of background noise to record")
    ap.add_argument("--out", default=str(FIRMWARE / "dataset"))
    args = ap.parse_args()

    with open(HERE / "keywords.csv", encoding="utf-8", newline="") as f:
        keywords = list(csv.DictReader(f))
    out = Path(args.out)

    print("This records the speaker's voice to train the wearable's keyword model.")
    print("The files stay on this computer. Continue only if the speaker agreed and signed the consent form.")
    if input("Has the speaker agreed? (yes/no) ").strip().lower() != "yes":
        return

    stream = Stream(args.port or find_port())
    try:
        for rep in range(1, args.reps + 1):
            order = keywords[:]
            random.shuffle(order)
            print(f"\n=== round {rep}/{args.reps} ===")
            for k in order:
                shown = k["say"] + (f"   ({k['romanised']})" if k["romanised"] else "")
                record_word(stream, out, k["label"], shown, args.speaker, rep)
            # Every other round is enough filler; the unknown class needs
            # variety more than repetition.
            if rep % 2 == 1:
                for i, w in enumerate(random.sample(FILLER, 5)):
                    record_word(stream, out, "_unknown", w, args.speaker, rep * 10 + i)

        if args.noise > 0:
            input(f"\nNoise: leave the device in a normal place (fan on, street, market) and press Enter. "
                  f"Recording {args.noise} s, nobody speaking to it.")
            stream.clear()
            for i in range(args.noise):
                save(out / "_noise" / f"_noise.{args.speaker}_{i:03d}.wav", stream.take(1.0))
            print(f"saved {args.noise} noise clips")
    finally:
        stream.close()
    print(f"\nDone. Upload with:  edge-impulse-uploader --category split \"{out}/*/*.wav\"")


if __name__ == "__main__":
    main()
