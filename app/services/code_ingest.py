import os, json, hashlib, torch
from datetime import datetime
from pathlib import Path
from tqdm import tqdm

MEMORY_PATH = Path("data/memory/code_index.json")

def hash_file(path: Path) -> str:
    """Calcule le hash SHA256 d’un fichier."""
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            sha.update(chunk)
    return sha.hexdigest()

def summarize_code_cuda(text: str, model=None) -> str:
    """Résumé rapide du contenu du code (CPU ou GPU si dispo)."""
    if not torch.cuda.is_available():
        # fallback CPU simple
        return text[:200] + "..." if len(text) > 200 else text
    else:
        # exemple simplifié : calcul de similarité ou compression vectorielle GPU
        tokens = torch.tensor([ord(c) for c in text[:1000]], dtype=torch.float32).cuda()
        mean_val = torch.mean(tokens).item()
        return f"[Résumé CUDA] moyenne={mean_val:.2f}, longueur={len(text)}"

def ingest_codebase(root_dir="app"):
    """Scanne le code source, détecte les changements, génère mémoire locale."""
    root = Path(root_dir)
    memory = {}

    if MEMORY_PATH.exists():
        try:
            memory = json.load(open(MEMORY_PATH, "r", encoding="utf8"))
        except json.JSONDecodeError:
            memory = {}

    updated_files = []
    for py_file in tqdm(list(root.rglob("*.py")), desc="🧠 Scan codebase"):
        h = hash_file(py_file)
        if py_file.as_posix() not in memory or memory[py_file.as_posix()]["hash"] != h:
            with open(py_file, "r", encoding="utf8") as f:
                content = f.read()
            summary = summarize_code_cuda(content)
            memory[py_file.as_posix()] = {
                "hash": h,
                "summary": summary,
                "last_update": datetime.now().isoformat()
            }
            updated_files.append(py_file.as_posix())

    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MEMORY_PATH, "w", encoding="utf8") as f:
        json.dump(memory, f, indent=2, ensure_ascii=False)

    return {"updated": updated_files, "total": len(memory)}
