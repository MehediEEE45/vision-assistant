# PlatformIO pre-upload hook (extra_scripts in platformio.ini).
#
# 1. Asks the running firmware to restart into the chip's USB boot loader
#    (the console's `dfu` command), so Upload needs no BOOT0/NRST presses.
#    Falls through quietly if the board is already in DFU mode, and says what
#    to press if it is not running this firmware at all.
# 2. Writes the image with STM32CubeProgrammer when it is installed, and with
#    dfu-util otherwise. dfu-util stops part-way on this chip: erasing one of
#    the H7's 128 KB sectors takes longer than it waits, and it fails with
#    LIBUSB error 74 on get_status. ST's own tool waits the erase out.

import glob
import os
import subprocess
import time

Import("env")  # noqa: F821  (provided by SCons)

HAND = "Hold BOOT0, press and release NRST, release BOOT0, then Upload again."
FLASH_BASE = "0x08000000"


def _dfu_util():
    pkg = env.PioPlatform().get_package_dir("tool-dfuutil")  # noqa: F821
    return os.path.join(pkg, "bin", "dfu-util") if pkg else "dfu-util"


def _cube_programmer():
    found = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        found += glob.glob(os.path.join(local, "stm32cube", "bundles", "programmer", "*", "bin",
                                        "STM32_Programmer_CLI.exe"))
    for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if root:
            p = os.path.join(root, "STMicroelectronics", "STM32Cube", "STM32CubeProgrammer", "bin",
                             "STM32_Programmer_CLI.exe")
            if os.path.isfile(p):
                found.append(p)
    return max(found, key=os.path.getmtime) if found else None


def _in_dfu(dfu):
    try:
        out = subprocess.run([dfu, "-l"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return False
    return "0483:df11" in out.lower()


def before_upload(source, target, env):
    dfu = _dfu_util()
    if _in_dfu(dfu):
        return
    try:
        import serial
        from serial.tools import list_ports
    except ImportError:
        print("pyserial is not available to PlatformIO. " + HAND)
        return
    ports = [p.device for p in list_ports.comports() if p.vid == 0x0483 and p.pid == 0x5740]
    if not ports:
        print("The board is not running this firmware (no USB serial port). " + HAND)
        return
    print(f"Asking the firmware on {ports[0]} to restart into DFU ...")
    try:
        with serial.Serial(ports[0], 115200, timeout=0.5) as s:
            # The leading newline ends any half-typed console line first.
            s.write(b"\ndfu\n")
            s.flush()
            time.sleep(0.2)
    except Exception as e:
        print(f"Could not open {ports[0]} ({e}). Close any serial monitor using it. " + HAND)
        return
    deadline = time.time() + 10
    while time.time() < deadline:
        if _in_dfu(dfu):
            print("Board is in DFU mode.")
            # Windows needs a moment to hand the new device to the next tool.
            time.sleep(1.0)
            return
        time.sleep(0.5)
    print("The board did not enter DFU mode. " + HAND)


_cube = _cube_programmer()
if _cube:
    env.Replace(UPLOADCMD=f'"{_cube}" -c port=USB1 -w "$SOURCE" {FLASH_BASE} -v -s {FLASH_BASE}')  # noqa: F821
else:
    print("STM32CubeProgrammer not found; uploading with dfu-util, which can stop with error 74.")
    env.Replace(UPLOADCMD=f'"{_dfu_util()}" -d 0483:df11 -a 0 -s {FLASH_BASE}:leave -D "$SOURCE"')  # noqa: F821

env.AddPreAction("upload", before_upload)  # noqa: F821
