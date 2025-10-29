# app/services/nn_personalizer.py
"""
Réseau de neurones léger pour personnalisation :
- Features = hashing TF de tokens (pas de vocab à maintenir)
- Modèle = MLP (D -> H -> 1) avec Sigmoid (score préférence ∈ [0,1])
- Entraînement incrémental sur feedback JSONL (like/dislike)
- Utilise CUDA si disponible (sinon CPU)
- Persistance: data/nn/personalizer.pt (+ config.json)
"""

from __future__ import annotations
import os
import json
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Dict, Any, Tuple, Optional

import torch
import torch.nn as nn
import torch.optim as optim

# --- Répertoires & fichiers ---
NN_DIR = Path("data") / "nn"
NN_DIR.mkdir(parents=True, exist_ok=True)
MODEL_PATH = NN_DIR / "personalizer.pt"
CFG_PATH = NN_DIR / "config.json"

FEEDBACK_DIR = Path("data") / "feedback"
FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
FEEDBACK_FILE = FEEDBACK_DIR / "feedback.jsonl"  # 1 JSON par ligne: {"text": "...", "label": 0/1, "meta": {...}}

_lock = threading.RLock()

# --- Device ---
DEVICE = torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu")


# --- Utilitaires texte (recyclés du style memory.py) ---
def _normalize_text(s: Any) -> str:
    if not isinstance(s, str):
        return ""
    return " ".join((s or "").strip().split())


def _tokenize(s: str) -> List[str]:
    s = s.lower()
    out: List[str] = []
    buff: List[str] = []
    for ch in s:
        if ch.isalnum():
            buff.append(ch)
        else:
            if buff:
                out.append("".join(buff))
                buff = []
    if buff:
        out.append("".join(buff))
    return out


def _hash_token(tok: str, dim: int) -> int:
    # hash stable basé sur Python
    return (hash(tok) & 0x7FFFFFFF) % dim


@dataclass
class NNConfig:
    dim: int = 4096   # taille hashing
    hidden: int = 256
    lr: float = 1e-3
    dropout: float = 0.1

    @classmethod
    def load(cls) -> "NNConfig":
        if CFG_PATH.exists():
            with CFG_PATH.open("r", encoding="utf-8") as f:
                d = json.load(f)
            return cls(**d)
        cfg = cls()
        cfg.save()
        return cfg

    def save(self):
        with CFG_PATH.open("w", encoding="utf-8") as f:
            json.dump(self.__dict__, f, ensure_ascii=False, indent=2)


class MLP(nn.Module):
    def __init__(self, dim: int, hidden: int, dropout: float = 0.1):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(dim, hidden),
            nn.ReLU(),
            nn.Dropout(p=dropout),
            nn.Linear(hidden, 1),
            nn.Sigmoid(),
        )

    def forward(self, x):
        return self.net(x)


class PreferenceNN:
    def __init__(self, cfg: Optional[NNConfig] = None):
        self.cfg = cfg or NNConfig.load()
        self.model = MLP(self.cfg.dim, self.cfg.hidden, self.cfg.dropout).to(DEVICE)
        self.opt = optim.Adam(self.model.parameters(), lr=self.cfg.lr)
        self._loaded = False
        self.load()

    # ---------- IO modèle ----------
    def save(self):
        to_save = {
            "state_dict": self.model.state_dict(),
            "opt": self.opt.state_dict(),
            "cfg": self.cfg.__dict__,
        }
        torch.save(to_save, MODEL_PATH)

    def load(self):
        if MODEL_PATH.exists():
            data = torch.load(MODEL_PATH, map_location=DEVICE)
            self.model.load_state_dict(data["state_dict"])
            try:
                self.opt.load_state_dict(data["opt"])
            except Exception:
                pass
            self._loaded = True

    # ---------- Features ----------
    def featurize(self, text: str) -> torch.Tensor:
        text = _normalize_text(text)
        toks = _tokenize(text)
        x = torch.zeros(self.cfg.dim, dtype=torch.float32)
        if not toks:
            return x
        # TF simple
        for t in toks:
            i = _hash_token(t, self.cfg.dim)
            x[i] += 1.0
        # L1-normalisation
        s = torch.sum(x)
        if s.item() > 0:
            x = x / s
        return x

    # ---------- Prédiction ----------
    @torch.no_grad()
    def predict_proba(self, texts: Iterable[str]) -> List[float]:
        self.model.eval()
        feats = []
        for t in texts:
            feats.append(self.featurize(t))
        if not feats:
            return []
        X = torch.stack(feats, dim=0).to(DEVICE)
        out = self.model(X).squeeze(1).detach().cpu().tolist()
        return [float(v) for v in out]

    @torch.no_grad()
    def score_one(self, text: str) -> float:
        r = self.predict_proba([text])
        return r[0] if r else 0.5

    # ---------- Entraînement ----------
    def _batchify(self, pairs: List[Tuple[str, int]], batch_size: int = 64):
        Xb: List[torch.Tensor] = []
        yb: List[float] = []
        for txt, lab in pairs:
            Xb.append(self.featurize(txt))
            yb.append(float(lab))
            if len(Xb) >= batch_size:
                yield torch.stack(Xb).to(DEVICE), torch.tensor(yb, dtype=torch.float32).to(DEVICE)
                Xb, yb = [], []
        if Xb:
            yield torch.stack(Xb).to(DEVICE), torch.tensor(yb, dtype=torch.float32).to(DEVICE)

    def fit_pairs(self, pairs: List[Tuple[str, int]], epochs: int = 2, batch_size: int = 64) -> Dict[str, Any]:
        if not pairs:
            return {"ok": False, "detail": "no data"}
        self.model.train()
        loss_fn = nn.BCELoss()
        total = 0.0
        steps = 0
        for _ in range(epochs):
            for X, y in self._batchify(pairs, batch_size=batch_size):
                self.opt.zero_grad()
                p = self.model(X).squeeze(1)
                loss = loss_fn(p, y)
                loss.backward()
                self.opt.step()
                total += float(loss.item())
                steps += 1
        self.save()
        return {"ok": True, "loss": (total / max(1, steps)), "steps": steps, "epochs": epochs}

    # ---------- Feedback JSONL ----------
    def load_feedback(self, limit: Optional[int] = None) -> List[Tuple[str, int]]:
        pairs: List[Tuple[str, int]] = []
        if not FEEDBACK_FILE.exists():
            return pairs
        with FEEDBACK_FILE.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if limit is not None and i >= limit:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                label = obj.get("label")
                if isinstance(label, str):
                    # "like"/"dislike"
                    label = 1 if label.lower() in ("like", "up", "good", "1", "👍") else 0
                elif isinstance(label, (int, float)):
                    label = 1 if float(label) >= 0.5 else 0
                else:
                    continue
                # On fabrique un texte fusionné (titre + résumé + url + query)
                parts = []
                for k in ("title", "summary", "url", "query", "text"):
                    v = obj.get(k)
                    if isinstance(v, str):
                        parts.append(v)
                text = " | ".join(parts)
                text = _normalize_text(text)
                if not text:
                    continue
                pairs.append((text, int(label)))
        return pairs

    def fit_from_feedback(self, limit: Optional[int] = None, epochs: int = 2) -> Dict[str, Any]:
        pairs = self.load_feedback(limit=limit)
        return self.fit_pairs(pairs, epochs=epochs)


# Objet global thread-safe
_personalizer: Optional[PreferenceNN] = None
_init_lock = threading.RLock()

def get_personalizer() -> PreferenceNN:
    global _personalizer
    with _init_lock:
        if _personalizer is None:
            _personalizer = PreferenceNN()
        return _personalizer


# Helpers simples utilisés ailleurs
def personalizer_predict(text: str) -> float:
    try:
        return get_personalizer().score_one(text)
    except Exception:
        return 0.5


def personalizer_train_from_feedback(limit: Optional[int] = None, epochs: int = 2) -> Dict[str, Any]:
    try:
        return get_personalizer().fit_from_feedback(limit=limit, epochs=epochs)
    except Exception as e:
        return {"ok": False, "detail": str(e)}
