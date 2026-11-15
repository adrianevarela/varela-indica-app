"""Varela Indica - busca as suas vendas e comissoes na Shopee e guarda CRIPTOGRAFADO para o painel.

Roda 4x por dia. Le o relatorio de conversoes (ultimos 90 dias), deixa so o que o painel precisa
e grava docs/ganhos.enc.json, que so abre com a senha do segredo PAINEL_SENHA.

Uso:
  python ganhos_shopee.py            -> atualiza docs/ganhos.enc.json
  python ganhos_shopee.py --resumo   -> so mostra totais no log (sem valores por pedido)
"""
import base64
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta

from buscar_shopee import APP_ID, SEGREDO, consultar
from postar import BRASILIA, PASTA, log

SENHA = os.environ.get("PAINEL_SENHA", "")
SAIDA = os.path.join(PASTA, "docs", "ganhos.enc.json")
DIAS = 90
JANELA = 30          # a Shopee aceita intervalos curtos: busca de 30 em 30 dias
ITERACOES = 200_000  # PBKDF2 (o painel usa o mesmo numero)

CAMPOS = """
  clickTime purchaseTime conversionId conversionStatus totalCommission netCommission estimatedTotalCommission
  buyerType utmContent device
  orders { orderId orderStatus items {
    itemId itemName itemPrice qty actualAmount refundAmount itemTotalCommission displayItemStatus
    completeTime imageUrl categoryLv1Name globalCategoryLv1Name channelType fraudStatus } }
"""


def num(v):
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def buscar_periodo(inicio, fim):
    """Todas as conversoes de um periodo, pagina por pagina."""
    nos, scroll, paginas = [], None, 0
    while True:
        args = f"purchaseTimeStart:{int(inicio.timestamp())}, purchaseTimeEnd:{int(fim.timestamp())}, limit:500"
        if scroll:
            args += f', scrollId:"{scroll}"'
        dados = consultar(f"{{conversionReport({args}){{nodes{{{CAMPOS}}} pageInfo{{hasNextPage scrollId}}}}}}", {})
        rel = dados["conversionReport"]
        nos += rel.get("nodes") or []
        info = rel.get("pageInfo") or {}
        paginas += 1
        if not info.get("hasNextPage") or not info.get("scrollId") or paginas > 40:
            return nos
        scroll = info["scrollId"]


def compactar(c):
    itens = []
    for pedido in c.get("orders") or []:
        for i in pedido.get("items") or []:
            itens.append({
                "id": str(i.get("itemId") or ""), "nome": (i.get("itemName") or "")[:90],
                "qtd": int(i.get("qty") or 0), "preco": num(i.get("itemPrice")),
                "pago": num(i.get("actualAmount")), "reembolso": num(i.get("refundAmount")),
                "comissao": num(i.get("itemTotalCommission")), "status": i.get("displayItemStatus") or pedido.get("orderStatus") or "",
                "categoria": i.get("globalCategoryLv1Name") or i.get("categoryLv1Name") or "",
                "foto": i.get("imageUrl") or "", "fraude": i.get("fraudStatus") or "",
            })
    return {
        "id": str(c.get("conversionId") or ""), "clique": c.get("clickTime"), "compra": c.get("purchaseTime"),
        "status": c.get("conversionStatus") or "", "comissao": num(c.get("netCommission") or c.get("totalCommission")),
        "estimada": num(c.get("estimatedTotalCommission")), "cliente": c.get("buyerType") or "",
        "canal": (c.get("utmContent") or "").split("-")[0], "aparelho": c.get("device") or "", "itens": itens,
    }


def criptografar(dados, senha):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    sal, iv = os.urandom(16), os.urandom(12)
    chave = hashlib.pbkdf2_hmac("sha256", senha.encode(), sal, ITERACOES, dklen=32)
    texto = json.dumps(dados, ensure_ascii=False, separators=(",", ":")).encode()
    cifra = AESGCM(chave).encrypt(iv, texto, None)  # cifra + etiqueta, igual ao WebCrypto
    b64 = lambda b: base64.b64encode(b).decode()
    return {"v": 1, "kdf": "PBKDF2-SHA256", "iter": ITERACOES, "sal": b64(sal), "iv": b64(iv), "dados": b64(cifra)}


def main():
    if not (APP_ID and SEGREDO):
        sys.exit("Faltam os segredos SHOPEE_APP_ID e SHOPEE_SECRET.")
    if not SENHA and "--resumo" not in sys.argv:
        sys.exit("Falta o segredo PAINEL_SENHA (a senha da aba Ganhos do painel).")
    agora = datetime.now(BRASILIA)
    conversoes, fim = {}, agora
    while fim > agora - timedelta(days=DIAS):
        inicio = max(fim - timedelta(days=JANELA), agora - timedelta(days=DIAS))
        try:
            for c in buscar_periodo(inicio, fim):
                conversoes[str(c.get("conversionId"))] = compactar(c)
        except Exception as e:
            log(f"Erro ao buscar {inicio:%d/%m}-{fim:%d/%m}: {e}")
        fim = inicio
        time.sleep(1)
    lista = sorted(conversoes.values(), key=lambda c: c.get("compra") or 0, reverse=True)
    log(f"{len(lista)} vendas nos ultimos {DIAS} dias.")  # o valor nao vai para o log, que e publico
    if "--resumo" in sys.argv:
        return
    dados = {"gerado": agora.isoformat(), "dias": DIAS, "conversoes": lista}
    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump(criptografar(dados, SENHA), f)
    log("docs/ganhos.enc.json atualizado (criptografado).")


if __name__ == "__main__":
    main()
