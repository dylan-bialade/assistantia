from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from app.services.chat_engine import chat_with_user

router = APIRouter()

@router.post("/chat")
def chat_api(message: str):
    reply = chat_with_user(message)
    return {"reply": reply}

@router.get("/chat_ui", response_class=HTMLResponse)
def chat_ui():
    return """
<!doctype html><html lang="fr"><head>
<meta charset="utf-8"><script src="https://cdn.tailwindcss.com"></script>
<title>Assistant IA — Chat</title></head>
<body class="bg-gray-50 p-6">
<h1 class="text-3xl font-bold mb-4">💬 Assistant IA — Chat (GPU)</h1>
<div id="log" class="bg-white rounded p-4 shadow mb-3 max-w-3xl h-[50vh] overflow-auto"></div>
<div class="flex gap-2">
  <input id="msg" class="border rounded px-3 py-2 w-2/3" placeholder="Parle avec ton assistant">
  <button onclick="send()" class="bg-indigo-600 text-white px-4 py-2 rounded">Envoyer</button>
</div>
<script>
const log = document.getElementById('log');
function add(role, text){
  const b = document.createElement('div');
  b.className = "mb-2";
  b.innerHTML = `<b>${role}:</b> ${text}`;
  log.appendChild(b); log.scrollTop = log.scrollHeight;
}
async function send(){
  const i = document.getElementById('msg'); const m = i.value.trim(); if(!m) return;
  add("Toi", m); i.value = "";
  const res = await fetch(`/chat?message=${encodeURIComponent(m)}`, {method:"POST"});
  const data = await res.json();
  add("Assistant", data.reply);
}
</script>
</body></html>
    """
