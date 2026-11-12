"""Create the project's environment on macOS or Windows. Run with Python 3.11."""

import argparse
import os
import subprocess
import sys
import venv
from pathlib import Path

LAB = Path(__file__).resolve().parent.parent
ROOT = LAB.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", action="store_true", help="Download all runtime models after installing")
    parser.add_argument("--notebooks", action="store_true", help="Include notebooks and training dependencies")
    parser.add_argument("--dev", action="store_true", help="Include pytest")
    parser.add_argument("--cpu", action="store_true", help="Use the CPU-only PyTorch wheel on Windows")
    args = parser.parse_args()
    if not (3, 11) <= sys.version_info[:2] < (3, 13):
        parser.error("Use Python 3.11 or 3.12 (3.11 is recommended)")
    env = ROOT / ".venv"
    python = env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(env)
    subprocess.run([str(python), "-m", "pip", "install", "--upgrade", "pip"], check=True)
    if args.cpu and os.name == "nt":
        subprocess.run([str(python), "-m", "pip", "install", "torch", "torchvision",
                        "--index-url", "https://download.pytorch.org/whl/cpu"], check=True)
    requirements = LAB / ("requirements-notebooks.txt" if args.notebooks else "requirements.txt")
    subprocess.run([str(python), "-m", "pip", "install", "-r", str(requirements)], cwd=LAB, check=True)
    # EasyOCR requires the headless distribution, which shares cv2 files with
    # the GUI wheel. Put the GUI files back last so the live window can open.
    subprocess.run([str(python), "-m", "pip", "install", "--force-reinstall", "--no-deps", "opencv-python>=4.10,<5"], check=True)
    if args.dev:
        subprocess.run([str(python), "-m", "pip", "install", "pytest>=8,<10"], check=True)
    if args.notebooks:
        subprocess.run([str(python), "-m", "ipykernel", "install", "--sys-prefix", "--name", "vision-ai-lab",
                        "--display-name", "Vision Assistant (project)"], check=True)
    if args.models:
        subprocess.run([str(python), str(LAB / "tools/download_models.py")], cwd=LAB, check=True)
    subprocess.run([str(python), "-m", "va_lab.doctor", "--skip-native"], cwd=LAB, check=True)
    print("Ready. Start lab/run_assistant.command (Mac) or lab/run_assistant.bat (Windows).")


if __name__ == "__main__":
    main()
