"""Varela Indica - responde sozinho os comentarios "EU QUERO" dos Reels.

Roda a cada 10 minutos. Para cada Reels dos ultimos 7 dias:
  1. le os comentarios novos;
  2. se o comentario pede o link ("quero", "eu quero", "manda o link"...), tenta mandar o link
     no direct (resposta privada ao comentario) e responde o comentario em publico.
O direct so funciona para todo mundo depois que a Meta aprovar o app (ate la, a Meta recusa
e o app faz so a resposta publica, apontando para o link na bio).
Guarda em respostas.json o que ja foi respondido (para nunca responder duas vezes).
"""
import json
import os
import random
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from postar import API_HOST, API_VER, BRASILIA, ESTADO, FB_PAGE, IG_ID, PASTA, TOKEN, ler_json, log, salvar_json

RESPOSTAS = os.path.join(PASTA, "respostas.json")
DIAS = 7  # a Meta so deixa responder no privado ate 7 dias depois do comentario
PEDIDO = re.compile(r"\b(eu\s*)?que+r+o+\b|\bmanda\b.*\blink\b|\blink\b.*\bpf|\bmeu\s+link\b", re.I)

PUBLICAS_DM = [
    "@{u} Oii! 💖 Te mandei o link no direct! Se não aparecer, olha em solicitações de mensagem 😉",
    "@{u} Mandei no seu direct! 💌 Corre que o preço pode mudar 🏃‍♀️",
    "@{u} Já tá no seu direct! 🛒💖",
]
PUBLICAS_BIO = [
    "@{u} Oii! 💖 O link tá na bio: toca no produto nº {n} 🛒",
    "@{u} Tá na bio, produto nº {n}! 💖 Corre que o preço pode mudar 🏃‍♀️",
    "@{u} É só tocar no link da bio e escolher o nº {n} 🛒✨",
]


def graph(metodo, caminho, dados=None, **params):
    params["access_token"] = TOKEN
    url = f"https://{API_HOST}/{API_VER}/{caminho}?{urllib.parse.urlencode(params)}"
    corpo = json.dumps(dados).encode() if dados is not None else None
    req = urllib.request.Request(url, data=corpo, method=metodo,
                                 headers={"Content-Type": "application/json"} if corpo else {})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(e.read().decode(errors="replace")[:300])


def mandar_direct(comentario_id, post, item):
    texto = (f"Oii! 💖 Aqui está o link do {post['produto']}:\n{item.get('link_dm') or post['link']}\n\n"
             f"⚠️ Preço pode mudar a qualquer momento. Qualquer dúvida é só chamar! ✨")
    graph("POST", f"{FB_PAGE}/messages", {"recipient": {"comment_id": comentario_id}, "message": {"text": texto}})


def main():
    if not TOKEN:
        raise SystemExit("Falta o token da Meta (FB_PAGE_TOKEN).")
    agora = datetime.now(BRASILIA)
    estado = ler_json(ESTADO, {"publicados": []})
    reg = ler_json(RESPOSTAS, {"respondidos": [], "por_post": {}, "direct_liberado": None})
    feitos = set(reg["respondidos"])
    novos = 0
    try:
        eu = (graph("GET", IG_ID, fields="username").get("username") or "").lower()
    except RuntimeError:
        eu = "varelaindica"
    for p in estado["publicados"]:
        if not p.get("reel") or datetime.fromisoformat(p["em"]) < agora - timedelta(days=DIAS):
            continue
        try:
            comentarios = graph("GET", f"{p['reel']}/comments", fields="id,text,username,timestamp", limit=100).get("data") or []
        except RuntimeError as e:
            if "does not exist" not in str(e):
                log(f"nº {p['numero']}: nao consegui ler os comentarios ({str(e)[:150]})")
            continue
        for c in comentarios:
            if c["id"] in feitos or not PEDIDO.search(c.get("text") or "") or (c.get("username") or "").lower() == eu:
                continue
            usuario = c.get("username") or ""
            direct = False
            if reg.get("direct_liberado") is not False or random.random() < 0.1:  # de vez em quando testa se liberou
                try:
                    mandar_direct(c["id"], p, p.get("item") or {})
                    direct = True
                    if not reg.get("direct_liberado"):
                        log("Direct funcionando! 🎉")
                    reg["direct_liberado"] = True
                except RuntimeError as e:
                    if reg.get("direct_liberado") is not False:
                        log(f"Direct recusado pela Meta (normal enquanto o app nao for aprovado): {str(e)[:150]}")
                    reg["direct_liberado"] = False
            modelo = random.choice(PUBLICAS_DM if direct else PUBLICAS_BIO)
            try:
                graph("POST", f"{c['id']}/replies", message=modelo.format(u=usuario, n=p["numero"]))
            except RuntimeError as e:
                log(f"nº {p['numero']}: nao consegui responder o comentario ({str(e)[:150]})")
                if not direct:
                    continue  # tenta de novo na proxima rodada
            feitos.add(c["id"])
            reg["respondidos"].append(c["id"])
            conta = reg["por_post"].setdefault(str(p["numero"]), {"pedidos": 0, "direct": 0})
            conta["pedidos"] += 1
            conta["direct"] += int(direct)
            novos += 1
            log(f"nº {p['numero']}: respondido {'(direct + publico)' if direct else '(publico)'}")
    reg["respondidos"] = reg["respondidos"][-3000:]
    reg["atualizado"] = agora.isoformat()
    salvar_json(RESPOSTAS, reg)
    log(f"{novos} pedidos de link respondidos nesta rodada.")


if __name__ == "__main__":
    main()
