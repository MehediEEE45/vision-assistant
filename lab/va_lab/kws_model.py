"""DS-CNN keyword spotter: training, evaluation, export, and live use.

Depthwise-separable CNN after Zhang et al., "Hello Edge" (2017), the model
family MLPerf Tiny uses for keyword spotting: small enough to port to the
wearable later, accurate enough to judge the vocabulary on a laptop now.
"""

import json
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from . import audio_io, config
from .features import N_MELS, NUM_FRAMES, LogMel

SR = config.SAMPLE_RATE


class DSCNN(nn.Module):
    def __init__(self, n_classes, channels=64, blocks=4, dropout=0.2):
        super().__init__()
        self.features = LogMel()
        self.norm = nn.BatchNorm2d(1)
        layers = [nn.Conv2d(1, channels, (10, 4), stride=(2, 2), padding=(5, 1), bias=False),
                  nn.BatchNorm2d(channels), nn.ReLU()]
        for _ in range(blocks):
            layers += [nn.Conv2d(channels, channels, 3, padding=1, groups=channels, bias=False),
                       nn.BatchNorm2d(channels), nn.ReLU(),
                       nn.Conv2d(channels, channels, 1, bias=False),
                       nn.BatchNorm2d(channels), nn.ReLU()]
        self.body = nn.Sequential(*layers)
        self.drop = nn.Dropout(dropout)
        self.fc = nn.Linear(channels, n_classes)
        self.config = {"n_classes": n_classes, "channels": channels, "blocks": blocks, "dropout": dropout}

    def classify(self, logmel):
        """[B, frames, mels] -> logits. Exported to ONNX on its own."""
        x = self.norm(logmel.unsqueeze(1))
        x = self.body(x)
        x = x.mean(dim=(2, 3))
        return self.fc(self.drop(x))

    def forward(self, wav):
        return self.classify(self.features(wav))


def _augment(wav, noise, train, gen):
    """Shift, gain and background noise, on the device, per batch."""
    if not train:
        return wav
    b = wav.shape[0]
    shift = torch.randint(-1600, 1601, (b,), device=wav.device, generator=gen)
    idx = (torch.arange(SR, device=wav.device)[None, :] - shift[:, None]).clamp(0, SR - 1)
    wav = torch.gather(wav, 1, idx)
    wav = wav * torch.empty(b, 1, device=wav.device).uniform_(0.6, 1.3, generator=gen)
    pick = torch.randint(0, noise.shape[0], (b,), device=wav.device, generator=gen)
    level = torch.empty(b, 1, device=wav.device).uniform_(0.0, 0.25, generator=gen)
    keep = (torch.rand(b, 1, device=wav.device, generator=gen) < 0.8).float()
    return (wav + noise[pick] * level * keep).clamp(-1.0, 1.0)


def train(ds, epochs=30, batch_size=128, lr=3e-3, channels=64, device=None, seed=0, log=print):
    """Trains on ds["training"], keeps the best ds["validation"] accuracy."""
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    torch.manual_seed(seed)
    gen = torch.Generator(device=device).manual_seed(seed)
    classes = ds["classes"]
    xtr = torch.from_numpy(ds["training"][0]).to(device)
    ytr = torch.from_numpy(ds["training"][1]).to(device)
    noise = torch.from_numpy(ds["noise"]).to(device)

    model = DSCNN(len(classes), channels=channels).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-3)
    steps = epochs * ((len(ytr) + batch_size - 1) // batch_size)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=steps)

    history, best, best_state = [], -1.0, None
    for epoch in range(1, epochs + 1):
        t0 = time.time()
        model.train()
        perm = torch.randperm(len(ytr), device=device, generator=gen)
        total, correct, loss_sum = 0, 0, 0.0
        for i in range(0, len(perm), batch_size):
            j = perm[i:i + batch_size]
            wav = _augment(xtr[j].float() / 32768.0, noise, True, gen)
            logits = model(wav)
            loss = F.cross_entropy(logits, ytr[j], label_smoothing=0.05)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            sched.step()
            loss_sum += loss.item() * len(j)
            correct += int((logits.argmax(1) == ytr[j]).sum())
            total += len(j)
        val_acc = evaluate(model, ds["validation"], device=device)["accuracy"]
        history.append({"epoch": epoch, "loss": loss_sum / total, "train_acc": correct / total,
                        "val_acc": val_acc, "seconds": time.time() - t0})
        log(f"epoch {epoch:2d}  loss {loss_sum / total:.3f}  train {correct / total:.3f}  "
            f"val {val_acc:.3f}  ({time.time() - t0:.1f}s)")
        if val_acc > best:
            best = val_acc
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)
    return model.cpu().eval(), history


@torch.no_grad()
def predict(model, x_int16, batch_size=512):
    """Class probabilities, on whichever device the model is on."""
    device = next(model.parameters()).device
    was_training = model.training
    model.eval()
    probs = []
    for i in range(0, len(x_int16), batch_size):
        wav = torch.from_numpy(x_int16[i:i + batch_size]).to(device).float() / 32768.0
        probs.append(F.softmax(model(wav), dim=1).cpu())
    model.train(was_training)
    return torch.cat(probs).numpy() if probs else np.zeros((0, 1))


def evaluate(model, split, device=None):
    x, y = split
    if len(y) == 0:
        return {"accuracy": float("nan"), "confusion": None}
    p = predict(model, x)
    pred = p.argmax(1)
    n = p.shape[1]
    conf = np.zeros((n, n), dtype=np.int64)
    np.add.at(conf, (y, pred), 1)
    return {"accuracy": float((pred == y).mean()), "confusion": conf}


def save(model, classes, path, history=None, vocab="demo"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"state": model.state_dict(), "config": model.config, "classes": classes,
                "vocab": vocab, "history": history or []}, path)
    path.with_suffix(".json").write_text(json.dumps({"classes": classes, "vocab": vocab,
                                                     "config": model.config}, indent=1))


def load(path):
    ckpt = torch.load(str(path), map_location="cpu", weights_only=False)
    cfg = ckpt["config"]
    model = DSCNN(cfg["n_classes"], channels=cfg["channels"], blocks=cfg["blocks"], dropout=cfg["dropout"])
    model.load_state_dict(ckpt["state"])
    return model.eval(), ckpt["classes"], ckpt.get("vocab", "demo")


def export_onnx(model, path):
    """The classifier on log-mel input [1, 97, 40]: the part a microcontroller
    runtime would take, with the front end implemented natively there."""
    path = Path(path)
    dummy = torch.zeros(1, NUM_FRAMES, N_MELS)

    class Core(nn.Module):
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, logmel):
            return self.m.classify(logmel)

    torch.onnx.export(Core(model.eval()), dummy, str(path), input_names=["logmel"],
                      output_names=["logits"], opset_version=17, dynamo=False)
    return path


class KeywordSpotter:
    """Classifies one push-to-talk window, the way the wearable does."""

    def __init__(self, path):
        self.model, self.classes, self.vocab = load(path)

    @torch.no_grad()
    def classify(self, audio):
        """(label, confidence, top3) for the loudest second of `audio` (float32)."""
        x = audio_io.loudest_second(np.asarray(audio, dtype=np.float32))
        p = F.softmax(self.model(torch.from_numpy(x)[None, :]), dim=1)[0].numpy()
        order = np.argsort(-p)
        top = [(self.classes[i], float(p[i])) for i in order[:3]]
        return top[0][0], top[0][1], top
