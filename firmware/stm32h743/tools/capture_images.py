#!/usr/bin/env python3
"""Take object-recognition training pictures through the wearable's own camera.

    python tools/capture_images.py --label chair                 # Enter for each picture
    python tools/capture_images.py --label street --every 2 --count 100
    python tools/capture_images.py --label test --count 1 --show # check orientation and colour

Why the device's camera: a model trained on phone photos loses accuracy on
an OV5640 behind a plastic window at chest height. Take the pictures with
the hardware the model will run on, from where it will be worn.

Output: images/<label>/<label>.<n>.png, 320x240. Then:

    edge-impulse-uploader --category split "images/*/*.png"

and draw the boxes in Edge Impulse Studio, using exactly these labels:
person chair door table bottle toilet rickshaw cng

Pictures of people need their consent. images/ is git-ignored; keep it so.
"""

import argparse
import struct
import sys
import time
from pathlib import Path

import numpy as np
import serial
import serial.tools.list_ports
from PIL import Image

HERE = Path(__file__).resolve().parent
FIRMWARE = HERE.parent
MAGIC = b"IMG1"
ERRORS = (b"no camera", b"camera busy", b"capture failed", b"capture timed out", b"send aborted")


def find_port():
    ports = [p for p in serial.tools.list_ports.comports() if p.vid == 0x0483]
    if len(ports) == 1:
        return ports[0].device
    names = ", ".join(p.device for p in serial.tools.list_ports.comports()) or "none"
    sys.exit(f"Could not pick the device automatically (serial ports: {names}). Pass --port COMx.")


def read_exact(ser, n, deadline):
    out = bytearray()
    while len(out) < n:
        if time.time() > deadline:
            raise TimeoutError(f"got {len(out)} of {n} bytes")
        out += ser.read(n - len(out))
    return bytes(out)


def snap(ser):
    ser.reset_input_buffer()
    ser.write(b"snap\n")
    deadline = time.time() + 6.0
    seen = bytearray()
    while True:
        if time.time() > deadline:
            text = seen.decode("utf-8", "replace").strip()
            raise TimeoutError(f"no picture from the device{': ' + text if text else ''}")
        seen += ser.read(64)
        i = seen.find(MAGIC)
        if i >= 0:
            rest = bytes(seen[i + len(MAGIC):])
            break
        for e in ERRORS:
            if e in seen:
                raise RuntimeError(seen.decode("utf-8", "replace").strip())
    header = rest[:10]
    if len(header) < 10:
        header += read_exact(ser, 10 - len(header), deadline)
    w, h, fmt, _reserved, length = struct.unpack("<HHBBI", header)
    if fmt != 1 or length != w * h * 2:
        raise RuntimeError(f"unexpected picture format {fmt}, {w}x{h}, {length} bytes")
    payload = rest[10:10 + length]
    if len(payload) < length:
        payload += read_exact(ser, length - len(payload), time.time() + 5.0)
    return w, h, payload


def to_image(w, h, payload):
    px = np.frombuffer(payload, dtype="<u2").reshape(h, w).astype(np.uint32)
    r = (px >> 11) & 0x1F
    g = (px >> 5) & 0x3F
    b = px & 0x1F
    rgb = np.dstack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)]).astype(np.uint8)
    return Image.fromarray(rgb, "RGB")


def next_index(folder, label):
    used = [int(p.stem.split(".")[-1]) for p in folder.glob(f"{label}.*.png") if p.stem.split(".")[-1].isdigit()]
    return max(used, default=0) + 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", required=True, help="folder name, e.g. chair, door, street, home")
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--every", type=float, default=0.0, help="seconds between pictures; 0 = press Enter each time")
    ap.add_argument("--show", action="store_true", help="open the last picture when done")
    ap.add_argument("--port")
    ap.add_argument("--out", default=str(FIRMWARE / "images"))
    args = ap.parse_args()

    folder = Path(args.out) / args.label
    folder.mkdir(parents=True, exist_ok=True)
    ser = serial.Serial(args.port or find_port(), 115200, timeout=0.2)
    last = None
    try:
        n = next_index(folder, args.label)
        for k in range(args.count):
            if args.every > 0:
                time.sleep(args.every if k else 0)
            else:
                input(f"[{k + 1}/{args.count}] point the device, then press Enter ")
            w, h, payload = snap(ser)
            last = folder / f"{args.label}.{n}.png"
            to_image(w, h, payload).save(last)
            print(f"saved {last.name}")
            n += 1
    finally:
        ser.close()
    if args.show and last is not None:
        Image.open(last).show()


if __name__ == "__main__":
    main()
