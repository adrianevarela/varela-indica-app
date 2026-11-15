"""Varela Indica - completa a fila sozinho com produtos da Shopee (API oficial de afiliados).

Roda todo dia de madrugada. Para os proximos 3 dias, todo horario (11h, 15h, 20h) que ainda
nao tem produto na fila ganha um produto da Shopee bem avaliado e muito vendido, com o seu
link de afiliada ja gerado pela propria Shopee.

Uso:
  python buscar_shopee.py            -> completa a fila
  python buscar_shopee.py --simular  -> so mostra o que escolheria
"""
import hashlib
import html
import json
import os
import random
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta

from postar import BRASILIA, ESTADO, FILA, hora_do, ler_json, log, salvar_json

APP_ID = os.environ.get("SHOPEE_APP_ID", "")
SEGREDO = os.environ.get("SHOPEE_SECRET", "")
URL = "https://open-api.affiliate.shopee.com.br/graphql"
DIAS = 3
HORARIOS = (11, 15, 20)
NOTA_MIN = 4.7
VENDAS_MIN = 1000
DESCONTO_MIN = 15      # % de desconto minimo
PRECO_MIN = 12.0       # evita amostras e coisas de R$ 3
NAO_REPETIR_DIAS = 60

# Temas que vao rodando para variar as categorias (troque a vontade)
TEMAS = [
    "achadinhos casa", "organizador", "cozinha utensilios", "airfryer acessorios", "limpeza casa",
    "skincare", "maquiagem", "cabelo", "acessorios celular", "fone bluetooth",
    "luminaria led", "banheiro", "lavanderia", "decoracao quarto", "garrafa termica",
    "pet", "infantil brinquedo", "fitness", "bolsa feminina", "papelaria", "viagem",
]

# Produtos com estas palavras nunca entram (replicas, "inspirados", coisas arriscadas)
PROIBIDAS = ["inspirad", "contratipo", "replica", "réplica", "similar", "1a linha", "primeira linha",
             "perfume", "fragrância", "fragrancia", "colônia", "colonia", "eau de", "importado",
             " 211 ", "selvage", "milion", "sauvage", "million", "amostra", "sample", "1g ", "1ml",
             "adulto", "sensual", "erótic", "erotic", " arma ", "faca tática", "vape", "cigarro"]


def consultar(query, variaveis):
    corpo = json.dumps({"query": query, "variables": variaveis}, separators=(",", ":"))
    for tentativa in range(4):
        ts = str(int(time.time()))
        assinatura = hashlib.sha256((APP_ID + ts + corpo + SEGREDO).encode()).hexdigest()
        req = urllib.request.Request(URL, data=corpo.encode(), method="POST", headers={
            "Content-Type": "application/json",
            "Authorization": f"SHA256 Credential={APP_ID}, Timestamp={ts}, Signature={assinatura}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            resposta = json.loads(r.read())
        if not resposta.get("errors"):
            return resposta["data"]
        time.sleep(6 * (tentativa + 1))  # a Shopee limita a velocidade: espera e tenta de novo
    raise RuntimeError(f"Shopee recusou: {resposta['errors']}")


def aprovado(p, usados):
    nome = f" {p.get('productName', '').lower()} "
    return (str(p["itemId"]) not in usados and p.get("offerLink")
            and float(p.get("ratingStar") or 0) >= NOTA_MIN
            and int(p.get("sales") or 0) >= VENDAS_MIN
            and int(p.get("priceDiscountRate") or 0) >= DESCONTO_MIN
            and float(p.get("priceMin") or 0) >= PRECO_MIN
            and not any(w in nome for w in PROIBIDAS))


BUSCA = """query($kw:String,$page:Int,$limit:Int,$sort:Int){
  productOfferV2(keyword:$kw,page:$page,limit:$limit,sortType:$sort){
    nodes{ itemId productName priceMin priceMax priceDiscountRate sales ratingStar imageUrl offerLink shopName }
  }
}"""


def reais(valor):
    return "R$ " + f"{float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


PEQUENAS = {"com", "de", "da", "do", "das", "dos", "para", "pra", "e", "a", "o", "em", "no", "na", "por", "|", "-", "+", "/"}


def nome_curto(nome, limite=36):
    nome = re.sub(r"^\s*(\[[^\]]*\]|【[^】]*】)\s*", "", nome)                     # [PROMO] no comeco
    nome = re.sub(r"^\s*(\d+\s*/\s*)*\d+\s*(pcs|pçs|peças|pecas|un|unid\w*|x)\b\.?\s*", "", nome, flags=re.I)
    nome = " ".join(nome.split())
    if sum(c.isupper() for c in nome) > 0.6 * max(1, sum(c.isalpha() for c in nome)):
        nome = nome.capitalize()                                                   # TUDO MAIUSCULO -> normal
    palavras = []
    for p in nome.split():
        if len(" ".join(palavras + [p])) > limite:
            break
        palavras.append(p)
    while len(palavras) > 1 and palavras[-1].lower() in PEQUENAS:
        palavras.pop()
    return " ".join(palavras) or nome[:limite]


def virar_item(p, quando):
    preco = float(p["priceMin"])
    desconto = int(p.get("priceDiscountRate") or 0)
    antes = preco / (1 - desconto / 100) if 0 < desconto < 95 else 0
    vendas = int(p.get("sales") or 0)
    vendas_txt = f"+{vendas // 1000} mil vendidos" if vendas >= 1000 else f"{vendas} vendidos"
    nota = f"{float(p['ratingStar']):.1f}".replace(".", ",")
    linha_preco = (f"💰 De <s>{reais(antes)}</s> por <b>{reais(preco)}</b> (-{desconto}%)" if antes
                   else f"💰 Por <b>{reais(preco)}</b>")
    curto = nome_curto(p["productName"])
    return {
        "quando": quando, "produto": curto, "loja": "Shopee", "itemId": str(p["itemId"]),
        "foto": p.get("imageUrl", ""), "video": "", "link": p["offerLink"], "preco": reais(preco),
        "texto": (f"🧡 <b>Achadinho da Shopee: {html.escape(curto)}</b>\n\n{html.escape(p['productName'][:160])}\n\n"
                  f"{linha_preco}\n⭐ {nota} · {vendas_txt}"),
    }


def main():
    simular = "--simular" in sys.argv
    if not (APP_ID and SEGREDO):
        sys.exit("Faltam os segredos SHOPEE_APP_ID e SHOPEE_SECRET (veja o LEIA-ME).")
    fila = ler_json(FILA, [])
    estado = ler_json(ESTADO, {"publicados": []})
    agora = datetime.now(BRASILIA)

    # horarios vazios nos proximos dias
    vazios = []
    for d in range(DIAS + 1):
        dia = (agora + timedelta(days=d)).date()
        for h in HORARIOS:
            quando = datetime(dia.year, dia.month, dia.day, h, tzinfo=BRASILIA)
            if quando > agora and not any(abs(hora_do(i) - quando) < timedelta(hours=1) for i in fila):
                vazios.append(quando)
    if not vazios:
        log("Fila completa para os proximos dias. Nada a fazer.")
        return

    limite = agora - timedelta(days=NAO_REPETIR_DIAS)
    usados = {i.get("itemId") for i in fila} | {
        p.get("item", {}).get("itemId") for p in estado["publicados"] if datetime.fromisoformat(p["em"]) > limite}
    temas = TEMAS[:]
    random.shuffle(temas)
    novos = []
    for quando in vazios:
        escolhido = None
        while temas and not escolhido:
            tema = temas.pop()
            try:
                nodes = consultar(BUSCA, {"kw": tema, "page": 1, "limit": 50, "sort": 2})["productOfferV2"]["nodes"]
            except Exception as e:
                log(f"  busca '{tema}' falhou: {e}")
                continue
            bons = [p for p in nodes if aprovado(p, usados)]
            # prioriza mais vendas, com um bonus para desconto maior
            bons.sort(key=lambda p: int(p.get("sales") or 0) * (1 + int(p.get("priceDiscountRate") or 0) / 100), reverse=True)
            if bons:
                escolhido = bons[0]
                log(f"{quando:%d/%m %Hh}: {nome_curto(escolhido['productName'])} ({tema})")
        if not escolhido:
            log("Acabaram os temas sem produto bom; o resto fica para amanha.")
            break
        usados.add(str(escolhido["itemId"]))
        novos.append(virar_item(escolhido, f"{quando:%Y-%m-%d %H:%M}"))

    if simular or not novos:
        print(json.dumps(novos, ensure_ascii=False, indent=1))
        return
    fila = sorted(fila + novos, key=hora_do)
    # limpa da fila o que ja passou ha mais de 7 dias (fica guardado no estado.json)
    fila = [i for i in fila if hora_do(i) > agora - timedelta(days=7)]
    salvar_json(FILA, fila)
    log(f"{len(novos)} produtos da Shopee adicionados a fila.")


if __name__ == "__main__":
    main()
