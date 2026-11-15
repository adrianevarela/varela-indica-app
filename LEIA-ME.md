# Varela Indica: posta sozinho (Instagram + Telegram)

Tudo roda no GitHub, de graça, **com o seu computador desligado**.

| Quando | O que o app faz sozinho |
|---|---|
| Todo dia às 6h | Confere os próximos 3 dias. Todo horário sem produto ganha um **achadinho da Shopee** bem avaliado (nota 4,6+, 500+ vendas), com o seu link de afiliada gerado pela própria Shopee. |
| 11h, 15h e 20h | Publica o **Reels** com a legenda pronta, repete o vídeo nos **Stories** e manda o produto no **grupo do Telegram** com o botão "🛒 Quero o meu". |
| Depois de cada post | Atualiza a sua **página "link na bio"**, com todos os produtos numerados. |
| Dias 1 e 15 | Renova a permissão do Instagram (ela vence a cada 60 dias). |

**De onde vêm os produtos**
- **Mercado Livre:** a tarefa de sábado do Claude (pesquisa de hype + links de afiliada). Ela precisa do seu login no Mercado Livre, então só funciona com o PC ligado no sábado. Se o PC estiver desligado, nada para: a Shopee preenche os horários.
- **Shopee:** 100% automático, pela API oficial de afiliados.
- **Shein:** a Shein não tem um jeito automático de gerar link de afiliada. Para postar um produto da Shein, coloque o link dela na fila (veja "Formato da fila") ou peça ao Claude.
- Se tudo acabar, o app repete um produto que foi postado há mais de 21 dias. O perfil nunca fica parado.

> Por que existe a página "link na bio"? O Instagram não deixa nenhum app colocar a figurinha de link nos Stories nem link clicável na legenda. A página resolve isso, e a legenda diz "toque no produto nº 12".

---

## Configuração (uma vez só, cerca de 40 minutos)

### 1. GitHub (onde o app roda)
1. Crie uma conta grátis em **github.com**.
2. Clique em **New repository**. Use o nome `varela-indica-app` e deixe como **Public**. Precisa ser público para a página e os robôs serem grátis. Ninguém vê suas senhas, porque elas ficam nos "Secrets".
3. Clique em **Add file → Upload files**, arraste **todo o conteúdo** desta pasta, inclusive a pasta `.github`, e clique em **Commit changes**.
4. Vá em **Settings → Pages**. Em *Branch*, escolha `main` e a pasta `/docs` e clique em **Save**. Sua página vai ser `https://SEU-USUARIO.github.io/varela-indica-app/`.

### 2. Instagram
1. Entre em **developers.facebook.com**, clique em **Meus apps → Criar app** e escolha o caso de uso **"Gerenciar mensagens e conteúdo no Instagram"**.
2. Em **Funções do app → Testadores do Instagram**, adicione `@varelaindica`. Depois, no app do Instagram, aceite o convite em *Configurações → Sites e apps*.
3. Em **"Gerar tokens de acesso"**, clique em **Adicionar conta**, entre com o @varelaindica e permita *instagram_business_basic* e *instagram_business_content_publish*.
4. Copie o **token** e o **ID da conta do Instagram**.

### 3. Shopee
1. Entre em **affiliate.shopee.com.br** com a sua conta de afiliada e vá em **Open API** (no menu ou no rodapé).
2. Peça o acesso e copie o **AppID** e o **Secret** (a "senha" da API).

### 4. Telegram
Abra `Documentos\telegram-token.txt` no Bloco de Notas e copie o conteúdo. É o token do robô @varela_indica_bot.

### 5. Token do GitHub
1. Vá em **github.com → foto → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.
2. Em *Repository access*, escolha **Only select repositories → varela-indica-app**.
3. Em *Permissions*, coloque **Contents: Read and write**, **Secrets: Read and write** e **Workflows: Read and write**.
4. Copie o token e salve também num arquivo novo, `Documentos\github-token.txt`.
5. Abra `Documentos\Varela Indica Telegram\enviar-fila.ps1` no Bloco de Notas e troque `SEU-USUARIO` pelo seu usuário do GitHub.

### 6. Guardar tudo no GitHub
No repositório, vá em **Settings → Secrets and variables → Actions → New repository secret** e crie um secret para cada linha:

| Nome | O que colar |
|---|---|
| `IG_TOKEN` | token do Instagram (passo 2) |
| `IG_USER_ID` | ID da conta do Instagram (passo 2) |
| `SHOPEE_APP_ID` | AppID da Shopee (passo 3) |
| `SHOPEE_SECRET` | Secret da Shopee (passo 3) |
| `TELEGRAM_TOKEN` | token do robô do Telegram (passo 4) |
| `GH_PAT` | token do GitHub (passo 5) |

Dá para ativar aos poucos: o app só posta nos canais que já têm o secret.

### 7. Testar (na aba **Actions** do repositório)
1. **Completar fila com a Shopee → Run workflow** com "simular" marcado. Mostra quais produtos ele escolheria.
2. Rode de novo **sem** "simular". Agora a fila fica preenchida.
3. **Postar no Instagram → Run workflow → simular** mostra as legendas, sem postar nada.
4. **Postar no Instagram → Run workflow → teste**, item `1`, posta de verdade na hora. Confira no Instagram e no Telegram.
5. Coloque o endereço da página na bio do Instagram.

Quando a primeira fila do Mercado Livre for para a nuvem, o PC para sozinho de mandar no Telegram, para não sair em dobro. Ele cria o arquivo `NUVEM-ATIVA.txt`; se apagar esse arquivo, o PC volta a mandar.

---

## Formato da fila (`fila.json`)
```json
[
  {
    "quando": "2026-11-16 11:00",
    "produto": "Mini processador",
    "loja": "Mercado Livre",
    "foto": "https://....jpg",
    "video": "https://....m3u8 (opcional)",
    "link": "https://meli.la/xxxx  (ou link da Shopee / Shein)",
    "preco": "R$ 18,69",
    "texto": "🧄 <b>Nunca mais pique alho na mão!</b> ... (texto do Telegram)",
    "legenda": "legenda do Instagram (opcional; use {bio} onde entra 'Link na bio: produto nº X')"
  }
]
```
Sem `legenda`, o app monta uma a partir do `texto`. Sem `video`, cria um vídeo com a `foto`, o nome e o preço.

## Onde conferir
- **Actions** mostra cada execução: verde funcionou, vermelho deu erro (clique para ver o motivo).
- `estado.json` lista tudo o que já foi postado.
- O GitHub manda e-mail quando alguma execução falha.
