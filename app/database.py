import sqlite3
from pathlib import Path

# Nom d'utilisateur
USER_NAME = "Dylan"

# Chemin de la base SQLite
DB_PATH = Path(__file__).resolve().parent / "prefs.db"


def db():
    """Retourne une connexion SQLite avec Row factory activée."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Crée les tables nécessaires si elles n’existent pas."""
    conn = db()
    cur = conn.cursor()

    # Table feedback (like/dislike)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        user TEXT NOT NULL,
        url TEXT NOT NULL,
        domain TEXT,
        title TEXT,
        label TEXT CHECK(label IN ('like','dislike')) NOT NULL
    );
    """)

    # Table des préférences utilisateur
    cur.execute("""
    CREATE TABLE IF NOT EXISTS prefs (
        id INTEGER PRIMARY KEY CHECK (id=1),
        user TEXT NOT NULL,
        preferred_domains TEXT DEFAULT '',
        blocked_domains TEXT DEFAULT '',
        preferred_keywords TEXT DEFAULT '',
        blocked_keywords TEXT DEFAULT '',
        like_weight REAL DEFAULT 1.0,
        dislike_weight REAL DEFAULT -1.0,
        domain_boost REAL DEFAULT 0.6,
        keyword_boost REAL DEFAULT 0.4,
        strict_block INTEGER DEFAULT 0
    );
    """)

    # Table d’historique des recherches (pour la nouveauté)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        user TEXT NOT NULL,
        query TEXT NOT NULL,
        url TEXT NOT NULL,
        domain TEXT
    );
    """)

    # S’assurer qu’une ligne prefs existe toujours pour l’utilisateur principal
    cur.execute("INSERT OR IGNORE INTO prefs (id, user) VALUES (1, ?)", (USER_NAME,))

    conn.commit()
    conn.close()


def reset_db(confirm: bool = False):
    """Réinitialise la base (efface tout)."""
    if not confirm:
        print("⚠️  Utilise reset_db(confirm=True) pour confirmer la suppression.")
        return
    conn = db()
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS feedback;")
    cur.execute("DROP TABLE IF EXISTS prefs;")
    cur.execute("DROP TABLE IF EXISTS history;")
    conn.commit()
    conn.close()
    print("🗑️ Base supprimée, relance init_db() pour la recréer.")


if __name__ == "__main__":
    print("🔧 Initialisation de la base de données...")
    init_db()
    print(f"✅ Base SQLite prête : {DB_PATH}")
