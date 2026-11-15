"""Varela Indica - posta sozinho no Instagram (Reels + Stories).

Roda no GitHub Actions nos horarios 11h, 15h e 20h (horario de Brasilia).
Le fila.json, posta o que ja chegou na hora e ainda nao foi postado,
guarda o que foi feito em estado.json e atualiza a pagina "link na bio" (docs/index.html).

Uso:
  python postar.py              -> posta o que estiver na hora
  python postar.py --simular    -> mostra o que faria, sem postar nada
  python postar.py --teste N    -> posta AGORA o item N da fila (1 = primeiro)
"""
import html
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

PASTA = os.path.dirname(os.path.abspath(__file__))
FILA = os.path.join(PASTA, "fila.json")
ESTADO = os.path.join(PASTA, "estado.json")
PAGINA = os.path.join(PASTA, "docs", "index.html")

BRASILIA = timezone(timedelta(hours=-3))
ATRASO_MAX = timedelta(hours=3)        # depois disso o post e pulado (nao posta fora de hora)
REPRISE_DIAS = 21                      # se a fila acabar, repete um produto postado ha mais de 21 dias
# Instagram + Facebook: com FB_PAGE_TOKEN (login pelo Facebook) o mesmo token publica no Instagram e na Pagina.
# Sem ele, usa IG_TOKEN (login pelo Instagram, so Instagram).
FB_TOKEN = os.environ.get("FB_PAGE_TOKEN", "")
FB_PAGE = os.environ.get("FB_PAGE_ID", "")
TOKEN = FB_TOKEN or os.environ.get("IG_TOKEN", "")
API_HOST = os.environ.get("IG_API_HOST") or ("graph.facebook.com" if FB_TOKEN else "graph.instagram.com")
API_VER = os.environ.get("IG_API_VERSION", "v27.0")
IG_ID = os.environ.get("IG_USER_ID", "me")
SITE = os.environ.get("SITE_URL", "")  # endereco da pagina link na bio
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "-1003821123476")  # grupo "Varela Indica"

HASHTAGS_GERAIS = "#achadinhos #promoção #ofertas #achadosdodia #viralnotiktok #varelaindica #comprasonline"
HASHTAGS_LOJA = {
    "Shopee": "#achadinhosshopee #shopee #shopeebrasil #achadosshopee",
    "Shein": "#shein #achadinhosshein #sheinbrasil #modafeminina",
    "Amazon": "#amazon #achadinhosamazon #amazonbrasil",
}
HASHTAGS_ML = "#achadinhosmercadolivre #mercadolivre #achadosmercadolivre"


def log(msg):
    print(f"{datetime.now(BRASILIA):%Y-%m-%d %H:%M:%S}  {msg}", flush=True)


def ler_json(caminho, padrao):
    if not os.path.exists(caminho):
        return padrao
    with open(caminho, encoding="utf-8-sig") as f:
        return json.load(f)


def salvar_json(caminho, dados):
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=1)


def chave(item):
    return f"{item['quando']} | {item['produto']}"


def hora_do(item):
    return datetime.strptime(item["quando"], "%Y-%m-%d %H:%M").replace(tzinfo=BRASILIA)


# ---------- textos ----------

def sem_html(texto):
    texto = re.sub(r"<s>(.*?)</s>", lambda m: "".join(c + "̶" for c in m.group(1)), texto or "")
    return html.unescape(re.sub(r"<[^>]+>", "", texto)).strip()


def preco_de(item):
    if item.get("preco"):
        return item["preco"]
    m = re.search(r"<b>(R\$\s?[\d.,]+)</b>", item.get("texto", ""))
    return m.group(1) if m else ""


def legenda_de(item, numero, facebook=False):
    """Legenda do Reels. Usa 'legenda' da fila se existir; senao monta a partir do texto do Telegram.
    No Facebook o link pode ir direto na legenda, entao troca o 'link na bio' pelo endereco da pagina."""
    if facebook and SITE:
        bio = f"🔗 Link do produto nº {numero}: {SITE}"
    else:
        bio = f"🔗 Link na bio: toque no produto nº {numero} 🛒"
    if item.get("legenda"):
        return item["legenda"].replace("{numero}", str(numero)).replace("{bio}", bio)
    return (
        f"{sem_html(item.get('texto', item['produto']))}\n\n"
        f"{bio}\n"
        "💬 Comenta EU QUERO que te mando o link!\n"
        "📲 Entra no nosso grupo do Telegram (link na bio) pra receber os achadinhos primeiro.\n\n"
        "⚠️ Preço pode mudar a qualquer momento.\n\n"
        f"{item.get('hashtags') or HASHTAGS_GERAIS + ' ' + HASHTAGS_LOJA.get(item.get('loja'), HASHTAGS_ML)}"
    )


# ---------- video ----------

def ffmpeg(*args):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-500:])


FONTE = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
MUSICAS = os.path.join(PASTA, "musicas")
VOZ = os.environ.get("VOZ", "pt-BR-FranciscaNeural")


def duracao(arquivo):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", arquivo],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def quebrar(texto, largura):
    linhas, atual = [], ""
    for p in texto.split():
        if atual and len(atual) + 1 + len(p) > largura:
            linhas.append(atual)
            atual = p
        else:
            atual = f"{atual} {p}".strip()
    return linhas + ([atual] if atual else [])


def baixar_video(item, pasta):
    """Devolve (MP4 vertical 1080x1920, veio_da_foto).
    Usa o video do anuncio (campo 'video': .m3u8 ou .mp4); sem video, cria um de 20 s a partir da foto."""
    saida = os.path.join(pasta, "base.mp4")
    if item.get("video"):
        try:
            ffmpeg("-i", item["video"], "-t", "90",
                   "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:white,fps=30",
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                   "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-movflags", "+faststart", saida)
            return saida, False
        except RuntimeError as e:
            log(f"  video do anuncio falhou ({e}); vou criar um com a foto")
    if not item.get("foto"):
        raise RuntimeError("produto sem video e sem foto")
    foto = os.path.join(pasta, "foto.jpg")
    urllib.request.urlretrieve(item["foto"], foto)
    zoom = ("scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:white,"
            "zoompan=z='min(zoom+0.0005,1.15)':d=600:s=1080x1920:fps=30")
    # nome em ate 2 linhas curtas + preco grande embaixo, tudo dentro da largura do video
    limpo = lambda t: re.sub(r"[^\w\s$,.!%-]", "", t).replace("%", "\\%").strip()
    linhas = [(limpo(l), 56) for l in quebrar(item["produto"], 24)[:2]]
    if preco_de(item):
        linhas.append((limpo(preco_de(item)), 84))
    y, textos = 1920 - 160 - sum(t + 40 for _, t in linhas), []
    for linha, tam in linhas:
        textos.append(f"drawtext=fontfile={FONTE}:text='{linha}':fontsize={tam}:fontcolor=white:box=1:"
                      f"boxcolor=0xE91E63@0.92:boxborderw=18:x=(w-text_w)/2:y={y}")
        y += tam + 40
    base = ["-loop", "1", "-i", foto, "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "20"]
    fim = ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", "-movflags", "+faststart", saida]
    try:
        ffmpeg(*base, "-vf", ",".join([zoom] + textos), *fim)
    except RuntimeError:
        ffmpeg(*base, "-vf", zoom, *fim)
    return saida, True


# ---------- audio: narracao + musica ----------

def reais_falado(valor):
    m = re.search(r"([\d.]+),(\d{2})", valor or "")
    if not m:
        return ""
    inteiro, cent = int(m.group(1).replace(".", "")), int(m.group(2))
    texto = f"{inteiro} {'real' if inteiro == 1 else 'reais'}"
    return texto + (f" e {cent} centavos" if cent else "")


def roteiro(item, numero):
    texto = item.get("texto", "")
    antes = re.search(r"<s>(R\$\s?[\d.,]+)</s>", texto)
    desconto = re.search(r"\(-(\d+)%\)", texto)
    loja = item.get("loja") or "Mercado Livre"
    partes = [f"Olha esse achadinho {'da' if loja == 'Shopee' else 'do' if loja == 'Mercado Livre' else 'da'} {loja}!",
              f"{item['produto']}."]
    agora = reais_falado(preco_de(item))
    if antes and agora:
        partes.append(f"De {reais_falado(antes.group(1))} por apenas {agora}!")
    elif agora:
        partes.append(f"Por apenas {agora}!")
    if desconto and int(desconto.group(1)) >= 15:
        partes.append(f"São {desconto.group(1)} por cento de desconto!")
    partes.append(f"O link tá na bio, produto número {numero}. Corre que o preço pode mudar!")
    return " ".join(partes)


def narracao(item, numero, pasta):
    saida = os.path.join(pasta, "voz.mp3")
    texto = roteiro(item, numero)
    r = subprocess.run(["edge-tts", "--voice", VOZ, "--rate=+8%", "--text", texto, "--write-media", saida],
                       capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(saida):
        log(f"  narracao falhou: {r.stderr[-200:]}")
        return None
    return saida


def com_audio(video, veio_da_foto, item, numero, pasta):
    """Coloca narracao (voz) + musica de fundo (se houver arquivos em musicas/) no video."""
    saida = os.path.join(pasta, "reel.mp4")
    voz = narracao(item, numero, pasta) if os.environ.get("NARRACAO", "sim") != "nao" else None
    musicas = [os.path.join(MUSICAS, m) for m in os.listdir(MUSICAS)
               if m.lower().endswith((".mp3", ".m4a", ".wav"))] if os.path.isdir(MUSICAS) else []
    musica = random.choice(musicas) if musicas else None
    if veio_da_foto:
        total = max(8.0, (duracao(voz) + 2.0) if voz else 10.0)
    else:
        total = duracao(video) or 30.0
    if not voz and not musica:
        if veio_da_foto:
            ffmpeg("-i", video, "-t", f"{total:.2f}", "-c", "copy", saida)
            return saida
        return video
    entradas, mistura, n = ["-i", video], [], 1
    if voz:
        entradas += ["-i", voz]
        mistura.append(f"[{n}:a]adelay=500|500,volume=1.8[v{n}]")
        n += 1
    if musica:
        entradas += ["-stream_loop", "-1", "-i", musica]
        mistura.append(f"[{n}:a]volume={'0.10' if voz else '0.35'},afade=t=out:st={max(0, total - 1.5):.2f}:d=1.5[v{n}]")
        n += 1
    rotulos = "".join(f"[v{i}]" for i in range(1, n))
    filtro = ";".join(mistura) + (f";{rotulos}amix=inputs={n - 1}:duration=longest:normalize=0[a]" if n > 2
                                  else f";{rotulos}anull[a]")
    try:
        ffmpeg(*entradas, "-filter_complex", filtro, "-map", "0:v", "-map", "[a]", "-t", f"{total:.2f}",
               "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-movflags", "+faststart", saida)
        log(f"  audio: {'narracao' if voz else ''}{' + ' if voz and musica else ''}{'musica ' + os.path.basename(musica) if musica else ''}")
        return saida
    except RuntimeError as e:
        log(f"  nao consegui colocar audio ({e}); vai o video original")
        return video


def preparar_video(item, numero, pasta):
    video, veio_da_foto = baixar_video(item, pasta)
    return com_audio(video, veio_da_foto, item, numero, pasta)


# ---------- Instagram ----------

def api(metodo, caminho, params=None):
    params = dict(params or {}, access_token=TOKEN)
    url = f"https://{API_HOST}/{API_VER}/{caminho}"
    dados = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url if metodo == "POST" else f"{url}?{dados.decode()}",
                                 data=dados if metodo == "POST" else None, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Instagram recusou ({e.code}): {e.read().decode(errors='replace')[:400]}")


def enviar_arquivo(container, arquivo):
    tamanho = os.path.getsize(arquivo)
    with open(arquivo, "rb") as f:
        req = urllib.request.Request(
            f"https://rupload.facebook.com/ig-api-upload/{API_VER}/{container}", data=f.read(), method="POST",
            headers={"Authorization": f"OAuth {TOKEN}", "offset": "0", "file_size": str(tamanho)})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"upload do video recusado ({e.code}): {e.read().decode(errors='replace')[:400]}")


def esperar_e_publicar(container):
    for _ in range(60):  # ate 10 minutos processando
        status = api("GET", container, {"fields": "status_code,status"})
        if status.get("status_code") == "FINISHED":
            return api("POST", f"{IG_ID}/media_publish", {"creation_id": container})["id"]
        if status.get("status_code") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram nao processou o video: {status.get('status')}")
        time.sleep(10)
    raise RuntimeError("Instagram demorou demais para processar o video")


def postar_video(tipo, arquivo, legenda=None):
    params = {"media_type": tipo, "upload_type": "resumable"}
    if tipo == "REELS":
        params.update(caption=legenda, share_to_feed="true")
    container = api("POST", f"{IG_ID}/media", params)["id"]
    enviar_arquivo(container, arquivo)
    return esperar_e_publicar(container)


def postar_story_foto(url_foto):
    container = api("POST", f"{IG_ID}/media", {"media_type": "STORIES", "image_url": url_foto})["id"]
    return esperar_e_publicar(container)


def video_story(video, numero):
    """O Instagram nao deixa app colocar figurinha de link: escreve no video onde achar o link."""
    saida = os.path.join(os.path.dirname(video), "story.mp4")
    fonte = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    # duas linhas que cabem na largura (o video e sempre 1080x1920), abaixo do nome do perfil no topo do story
    estilo = f"fontfile={fonte}:fontcolor=white:box=1:boxcolor=0xE91E63@0.92:x=(w-text_w)/2"
    faixa = (f"drawtext={estilo}:text='LINK NA BIO':fontsize=80:boxborderw=24:y=290,"
             f"drawtext={estilo}:text='produto nº {numero}':fontsize=60:boxborderw=18:y=420")
    try:
        ffmpeg("-i", video, "-vf", faixa, "-t", "60", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
               "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", saida)
        return saida
    except RuntimeError as e:
        log(f"  nao consegui escrever no story ({e}); vai sem a faixa")
        return video


def postar(item, numero, video):
    reel = postar_video("REELS", video, legenda_de(item, numero))
    log(f"  Reels publicado no Instagram (id {reel})")
    story = None
    try:
        story = postar_video("STORIES", video_story(video, numero))
    except RuntimeError as e:
        log(f"  story em video falhou ({e}); tentando com a foto")
        try:
            story = postar_story_foto(item["foto"]) if item.get("foto") else None
        except RuntimeError as e2:
            log(f"  story com a foto tambem falhou ({e2})")
    log(f"  Story publicado (id {story})" if story else "  Story NAO publicado")
    return reel, story


# ---------- Facebook (Reels na Pagina) ----------

def postar_facebook(item, numero, video):
    inicio = api("POST", f"{FB_PAGE}/video_reels", {"upload_phase": "start"})
    tamanho = os.path.getsize(video)
    with open(video, "rb") as f:
        req = urllib.request.Request(
            inicio.get("upload_url") or f"https://rupload.facebook.com/video-upload/{API_VER}/{inicio['video_id']}",
            data=f.read(), method="POST",
            headers={"Authorization": f"OAuth {TOKEN}", "offset": "0", "file_size": str(tamanho)})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"upload no Facebook recusado ({e.code}): {e.read().decode(errors='replace')[:400]}")
    api("POST", f"{FB_PAGE}/video_reels", {"upload_phase": "finish", "video_id": inicio["video_id"],
                                           "video_state": "PUBLISHED", "description": legenda_de(item, numero, facebook=True)})
    log(f"  Reels publicado no Facebook (id {inicio['video_id']})")
    return inicio["video_id"]


# ---------- Telegram ----------

def telegram(metodo, dados):
    req = urllib.request.Request(f"https://api.telegram.org/bot{TG_TOKEN}/{metodo}", method="POST",
                                 data=json.dumps(dados).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Telegram recusou ({e.code}): {e.read().decode(errors='replace')[:300]}")


def enviar_telegram(item):
    texto = f"{item.get('texto') or html.escape(item['produto'])}\n\n⚠️ Preço pode mudar a qualquer momento."
    dados = {"chat_id": TG_CHAT, "parse_mode": "HTML",
             "reply_markup": {"inline_keyboard": [[{"text": "🛒 Quero o meu", "url": item["link"]}]]}}
    if item.get("foto"):
        try:
            return telegram("sendPhoto", dict(dados, photo=item["foto"], caption=texto))
        except RuntimeError as e:
            log(f"  foto no Telegram falhou ({e}); mandando so o texto")
    return telegram("sendMessage", dict(dados, text=texto))


# ---------- pagina link na bio ----------

def gerar_pagina(estado):
    cards = []
    for p in sorted(estado["publicados"], key=lambda p: p["numero"], reverse=True)[:30]:
        foto = f'<img src="{html.escape(p.get("foto", ""))}" alt="" loading="lazy">' if p.get("foto") else ""
        cards.append(
            f'<a class="card" href="{html.escape(p["link"])}" target="_blank" rel="noopener">'
            f'<span class="num">nº {p["numero"]}</span>{foto}'
            f'<span class="nome">{html.escape(p["produto"])}</span>'
            f'<span class="loja">{html.escape(p.get("loja") or "Mercado Livre")}</span>'
            f'<span class="preco">{html.escape(p.get("preco", ""))}</span>'
            f'<span class="btn">🛒 Quero o meu</span></a>')
    modelo = open(os.path.join(PASTA, "modelo_pagina.html"), encoding="utf-8").read()
    os.makedirs(os.path.dirname(PAGINA), exist_ok=True)
    with open(PAGINA, "w", encoding="utf-8") as f:
        f.write(modelo.replace("{{CARDS}}", "\n".join(cards) or "<p>Em breve os próximos achadinhos 💖</p>")
                      .replace("{{ATUALIZADO}}", f"{datetime.now(BRASILIA):%d/%m/%Y %H:%M}"))


# ---------- principal ----------

def canais():
    """Canais configurados: so posta onde o segredo existe."""
    return [c for c, ok in (("ig", TOKEN), ("fb", FB_TOKEN and FB_PAGE), ("tg", TG_TOKEN)) if ok]


NOMES = {"ig": "Instagram", "fb": "Facebook", "tg": "Telegram"}


def marca(canal, item):
    return f"{canal} | {item.get('_marca') or chave(item)}"


def proximos_da_vez(fila, estado, agora, ativos):
    feitos = set(estado["feitos"])
    da_vez = []
    for item in fila:
        faltam = [c for c in ativos if marca(c, item) not in feitos]
        if not faltam:
            continue
        atraso = agora - hora_do(item)
        if atraso < timedelta(0):
            continue
        if atraso > ATRASO_MAX:
            log(f"PULADO (atrasado demais): {chave(item)}")
            estado["feitos"].extend(marca(c, item) for c in faltam)
            continue
        da_vez.append(item)
    return da_vez


def reprise(fila, estado, agora):
    """Se nao ha nada na fila para este horario, repete um produto antigo (para nunca ficar sem post)."""
    horario = agora.replace(minute=0, second=0, microsecond=0)
    if horario.hour not in (11, 15, 20) or agora - horario > ATRASO_MAX:
        return None
    rotulo = f"reprise | {horario:%Y-%m-%d %H:%M}"
    if any(rotulo in f for f in estado["feitos"]) or any(abs(hora_do(i) - horario) < timedelta(hours=1) for i in fila):
        return None
    limite = agora - timedelta(days=REPRISE_DIAS)
    antigos = [p for p in estado["publicados"] if p.get("item") and datetime.fromisoformat(p["em"]) < limite]
    if not antigos:
        return None
    escolhido = min(antigos, key=lambda p: p.get("reprises", 0))
    escolhido["reprises"] = escolhido.get("reprises", 0) + 1
    item = dict(escolhido["item"], quando=f"{horario:%Y-%m-%d %H:%M}")
    item["_marca"] = rotulo
    return item


def main():
    if "--video" in sys.argv:  # so monta o video (com som e faixa do story) para conferir, sem postar
        item = ler_json(FILA, [])[int(sys.argv[sys.argv.index("--video") + 1]) - 1]
        os.makedirs(os.path.join(PASTA, "previa"), exist_ok=True)
        with tempfile.TemporaryDirectory() as pasta:
            video = preparar_video(item, 99, pasta)
            story = video_story(video, 99)
            for origem, nome in ((video, "reels.mp4"), (story, "story.mp4")):
                with open(origem, "rb") as a, open(os.path.join(PASTA, "previa", nome), "wb") as b:
                    b.write(a.read())
        log(f"Previa pronta: {item['produto']} ({duracao(os.path.join(PASTA, 'previa', 'reels.mp4')):.0f} s)")
        log("Narracao: " + roteiro(item, 99))
        return

    simular = "--simular" in sys.argv
    teste = int(sys.argv[sys.argv.index("--teste") + 1]) if "--teste" in sys.argv else 0
    ativos = canais() or (["ig", "tg"] if simular else [])
    if not ativos:
        sys.exit("Nenhum canal configurado: crie o segredo IG_TOKEN e/ou TELEGRAM_TOKEN (veja o LEIA-ME).")

    fila = ler_json(FILA, [])
    estado = ler_json(ESTADO, {"contador": 0, "feitos": [], "publicados": []})
    agora = datetime.now(BRASILIA)

    if teste:
        itens = [fila[teste - 1]]
    else:
        itens = proximos_da_vez(fila, estado, agora, ativos)
        if not itens:
            r = reprise(fila, estado, agora)
            itens = [r] if r else []
    if not itens:
        log("Nada para postar agora.")
        proximo = min((i for i in fila if hora_do(i) > agora), key=hora_do, default=None)
        log(f"Proximo da fila: {chave(proximo)}" if proximo else "ATENCAO: a fila acabou!")

    for item in itens:
        feitos = set(estado["feitos"])
        faltam = [c for c in ativos if teste or marca(c, item) not in feitos]
        registro = next((p for p in estado["publicados"] if p.get("chave") == chave(item)), None)
        numero = registro["numero"] if registro else estado["contador"] + 1
        log(f"{'[SIMULACAO] ' if simular else ''}nº {numero}: {chave(item)} -> {', '.join(faltam)}")
        if simular:
            print("-" * 40 + "\n" + legenda_de(item, numero) + "\n\n🎙️ Narracao: " + roteiro(item, numero) + "\n" + "-" * 40)
            continue
        if not registro:
            registro = {"numero": numero, "chave": chave(item), "em": agora.isoformat(), "produto": item["produto"],
                        "loja": item.get("loja", ""), "link": item["link"], "foto": item.get("foto", ""),
                        "preco": preco_de(item), "item": {k: v for k, v in item.items() if k not in ("quando", "_marca")}}
        with tempfile.TemporaryDirectory() as pasta:
            video = None
            for canal in faltam:
                try:
                    if canal in ("ig", "fb") and not video:
                        video = preparar_video(item, numero, pasta)  # o mesmo video serve para Instagram e Facebook
                    if canal == "ig":
                        registro["reel"], registro["story"] = postar(item, numero, video)
                    elif canal == "fb":
                        registro["facebook"] = postar_facebook(item, numero, video)
                    else:
                        enviar_telegram(item)
                        log("  Telegram enviado")
                except Exception as e:
                    log(f"ERRO no {NOMES[canal]} ({chave(item)}): {e}")
                    continue
                estado["feitos"].append(marca(canal, item))
                if registro not in estado["publicados"]:
                    estado["contador"] = numero
                    estado["publicados"].append(registro)

    if not simular:
        estado["feitos"] = estado["feitos"][-500:]
        salvar_json(ESTADO, estado)
        gerar_pagina(estado)
        if SITE:
            log(f"Pagina link na bio: {SITE}")


if __name__ == "__main__":
    main()
