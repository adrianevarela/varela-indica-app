"""Varela Indica - junta as metricas dos posts e do perfil para o painel (docs/metricas.json).

Roda a cada 3 horas. Para cada post dos ultimos 30 dias busca: link do post, capa do video,
visualizacoes, alcance, curtidas, comentarios, salvamentos e compartilhamentos (Instagram),
metricas do Story (enquanto ele existe) e do Reels no Facebook. Do perfil: seguidores,
alcance, visitas ao perfil e cliques no link da bio. Do Telegram: membros do grupo.

Cada metrica e pedida separada: se a Meta recusar uma (falta de permissao, nome mudou),
as outras continuam. Valores de dinheiro NUNCA entram aqui (este arquivo e publico).
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from postar import (API_HOST, API_VER, BRASILIA, ESTADO, FB_PAGE, IG_ID, PASTA, TG_CHAT, TG_TOKEN, TOKEN,
                    ler_json, log, salvar_json)

SAIDA = os.path.join(PASTA, "docs", "metricas.json")
DIAS_POSTS = 30
recusadas = set()  # metricas que a Meta recusou nesta rodada (para nao insistir)


def graph(caminho, **params):
    params["access_token"] = TOKEN
    url = f"https://{API_HOST}/{API_VER}/{caminho}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(e.read().decode(errors="replace")[:300])


def valor_insight(item):
    if "total_value" in item:
        return item["total_value"].get("value")
    vals = item.get("values") or []
    return vals[-1].get("value") if vals else None


def insights(objeto, metricas, chave_cache, **extra):
    """Pede cada metrica separada; devolve {nome: valor} so com as que funcionaram."""
    saida = {}
    for m in metricas:
        if (chave_cache, m) in recusadas:
            continue
        try:
            dados = graph(f"{objeto}/insights", metric=m, **extra).get("data") or []
            if dados:
                v = valor_insight(dados[0])
                if isinstance(v, (int, float)):
                    saida[m] = v
        except RuntimeError as e:
            recusadas.add((chave_cache, m))
            log(f"  metrica '{m}' ({chave_cache}) indisponivel: {str(e)[:120]}")
    return saida


def metricas_post(p):
    info = {"numero": p["numero"]}
    if p.get("reel"):
        try:
            m = graph(p["reel"], fields="permalink,thumbnail_url,like_count,comments_count,timestamp")
            info.update(link_ig=m.get("permalink"), capa=m.get("thumbnail_url"),
                        curtidas=m.get("like_count"), comentarios=m.get("comments_count"))
        except RuntimeError as e:
            if "does not exist" in str(e):
                log(f"  nº {p['numero']}: post apagado no Instagram")
                return {"numero": p["numero"], "apagado": True}
            log(f"  nº {p['numero']}: nao consegui ler o Reels ({str(e)[:100]})")
        ins = insights(p["reel"], ["views", "reach", "likes", "comments", "saved", "shares", "total_interactions"], "reel")
        info.update({
            "views": ins.get("views"), "alcance": ins.get("reach"), "salvos": ins.get("saved"),
            "compartilhamentos": ins.get("shares"), "interacoes": ins.get("total_interactions"),
        })
        info["curtidas"] = ins.get("likes", info.get("curtidas"))
        info["comentarios"] = ins.get("comments", info.get("comentarios"))
    if p.get("story"):
        st = insights(p["story"], ["reach", "replies", "shares", "total_interactions"], "story")
        if st:
            info["story"] = {"alcance": st.get("reach"), "respostas": st.get("replies"), "interacoes": st.get("total_interactions")}
    if p.get("facebook"):
        try:
            fb = graph(p["facebook"], fields="permalink_url")
            if fb.get("permalink_url"):
                link = fb["permalink_url"]
                info["link_fb"] = link if link.startswith("http") else "https://www.facebook.com" + link
        except RuntimeError:
            pass
        fbi = {}
        try:
            dados = graph(f"{p['facebook']}/video_insights").get("data") or []
            for d in dados:
                if d.get("name") in ("blue_reels_play_count", "fb_reels_total_plays") and valor_insight(d) is not None:
                    fbi["views"] = valor_insight(d)
        except RuntimeError:
            pass
        if fbi.get("views") is not None:
            info["views_fb"] = fbi["views"]
    return {k: v for k, v in info.items() if v is not None}


def metricas_perfil(hoje):
    perfil = {}
    try:
        perfil.update(graph(IG_ID, fields="followers_count,media_count,username"))
    except RuntimeError as e:
        log(f"  perfil: {str(e)[:120]}")
    # totais de ontem (dia fechado) e de hoje ate agora
    for nome, dia in (("ontem", hoje - timedelta(days=1)), ("hoje", hoje)):
        inicio = datetime(dia.year, dia.month, dia.day, tzinfo=BRASILIA)
        perfil[nome] = insights(IG_ID, ["reach", "views", "profile_views", "website_clicks", "accounts_engaged", "follows_and_unfollows"],
                                "conta", period="day", metric_type="total_value",
                                since=int(inicio.timestamp()), until=int((inicio + timedelta(days=1)).timestamp()))
    return perfil


def membros_telegram():
    if not TG_TOKEN:
        return None
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{TG_TOKEN}/getChatMemberCount?chat_id={TG_CHAT}", timeout=30) as r:
            return json.loads(r.read()).get("result")
    except Exception:
        log("  Telegram: nao consegui ler o numero de membros")
        return None


def main():
    if not TOKEN:
        raise SystemExit("Falta o token da Meta (FB_PAGE_TOKEN).")
    agora = datetime.now(BRASILIA)
    estado = ler_json(ESTADO, {"publicados": [], "feitos": []})
    antigo = ler_json(SAIDA, {})
    limite = agora - timedelta(days=DIAS_POSTS)
    posts = {}
    for p in estado["publicados"]:
        if datetime.fromisoformat(p["em"]) < limite:
            continue
        velho = (antigo.get("posts") or {}).get(str(p["numero"])) or {}
        if velho.get("apagado"):  # post apagado: nao pergunta de novo
            posts[str(p["numero"])] = velho
            continue
        posts[str(p["numero"])] = metricas_post(p)
        # guarda o ultimo valor do story (depois de 24 h a Meta apaga)
        if "story" not in posts[str(p["numero"])] and velho.get("story"):
            posts[str(p["numero"])]["story"] = velho["story"]
    perfil = metricas_perfil(agora.date())
    tg = membros_telegram()
    # historico diario (seguidores e membros do Telegram), 90 dias
    historico = antigo.get("historico") or {}
    dia = agora.strftime("%Y-%m-%d")
    historico[dia] = {k: v for k, v in {"seguidores": perfil.get("followers_count"), "telegram": tg}.items() if v is not None}
    ontem = (agora - timedelta(days=1)).strftime("%Y-%m-%d")
    if ontem in historico and perfil.get("ontem"):
        historico[ontem]["conta"] = perfil["ontem"]  # dia fechado, numeros definitivos
    historico = dict(sorted(historico.items())[-90:])
    salvar_json(SAIDA, {"gerado": agora.isoformat(), "posts": posts, "perfil": perfil, "telegram": tg, "historico": historico})
    log(f"Metricas de {len(posts)} posts atualizadas. Seguidores: {perfil.get('followers_count')}. Telegram: {tg}.")


if __name__ == "__main__":
    main()
