# app/models/code_change.py
from pydantic import BaseModel, Field
from typing import List

class CodeChange(BaseModel):
    line_number: int = Field(..., ge=1, description="Numéro de ligne (1-based)")
    before: str = Field(..., description="Texte avant le changement")
    after: str = Field(..., description="Texte après (peut être vide pour suppression)")

class CodeReport(BaseModel):
    file_path: str = Field(..., description="Chemin relatif du fichier à modifier (dans le projet)")
    changes: List[CodeChange] = Field(..., description="Liste ordonnée des changements")
    objective: str = Field("", description="Contexte/objectif du changement (optionnel)")
