"""Log-mel features, in torch so training (GPU) and inference share one implementation."""

import math

import torch

from . import config

SR = config.SAMPLE_RATE
N_FFT = 512
WIN = 400   # 25 ms
HOP = 160   # 10 ms
N_MELS = 40
FMIN, FMAX = 20.0, 7600.0
NUM_FRAMES = 1 + (SR - N_FFT) // HOP  # 97 for one second


def _hz_to_mel(f):
    return 2595.0 * math.log10(1.0 + f / 700.0)


def _mel_to_hz(m):
    return 700.0 * (10 ** (m / 2595.0) - 1.0)


def mel_filterbank():
    n_bins = N_FFT // 2 + 1
    mels = torch.linspace(_hz_to_mel(FMIN), _hz_to_mel(FMAX), N_MELS + 2)
    hz = torch.tensor([_mel_to_hz(float(m)) for m in mels])
    bins = torch.linspace(0, SR / 2, n_bins)
    fb = torch.zeros(n_bins, N_MELS)
    for i in range(N_MELS):
        lo, mid, hi = hz[i], hz[i + 1], hz[i + 2]
        up = (bins - lo) / (mid - lo)
        down = (hi - bins) / (hi - mid)
        fb[:, i] = torch.clamp(torch.minimum(up, down), min=0.0)
    return fb


class LogMel(torch.nn.Module):
    """[B, samples] in -1..1  ->  [B, frames, N_MELS]."""

    def __init__(self):
        super().__init__()
        window = torch.zeros(N_FFT)
        window[:WIN] = torch.hann_window(WIN)
        self.register_buffer("window", window)
        self.register_buffer("fb", mel_filterbank())

    def forward(self, wav):
        spec = torch.stft(wav, n_fft=N_FFT, hop_length=HOP, win_length=N_FFT, window=self.window,
                          center=False, return_complex=True)
        power = spec.real ** 2 + spec.imag ** 2  # [B, bins, frames]
        mel = power.transpose(1, 2) @ self.fb
        return torch.log(mel + 1e-6)
