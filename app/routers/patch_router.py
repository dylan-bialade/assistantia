from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pathlib import Path

router = APIRouter(tags=["patch"])

class PatchIn(BaseModel):
    file_path: str
    new_code: str

@router.post("/apply_patch")
def apply_patch(patch: PatchIn):
    path = Path(patch.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Fichier introuvable")

    backup_path = path.with_suffix(".bak")
    path.rename(backup_path)  # Sauvegarde de sécurité

    with open(path, "w", encoding="utf8") as f:
        f.write(patch.new_code)

    return {"detail": f"Code mis à jour avec succès dans {path.name}"}
