# Guia de deploy: publicar a web gratuitamente

Este guia leva o projeto do GitHub até uma URL pública no **Streamlit Community Cloud**, usando as camadas gratuitas dos quatro bancos.

> **Status honesto desta documentação.** Os limites dos planos gratuitos abaixo foram conferidos na documentação dos provedores em **19/11/2026**, mas planos gratuitos mudam: confirme antes de depender deles. O deploy real no Streamlit Cloud e a conexão com Astra DB e AuraDB reais **não foram executados por quem escreveu este guia** (exigem as suas contas e credenciais). Os passos foram escritos a partir da documentação e do comportamento do código, que foi testado com bancos simulados.

## Visão geral

```
GitHub (código, sem segredos) → Streamlit Community Cloud (app + Secrets)
                                      │
        ┌─────────────┬───────────────┼───────────────┐
   MongoDB Atlas   Redis Cloud   Astra DB         Neo4j AuraDB
      (M0)          (Free)       (Cassandra)        (Free)
```

Ordem recomendada: **1)** preparar o repositório, **2)** criar os bancos, **3)** gerar as credenciais da aplicação, **4)** publicar, **5)** carregar os dados de exemplo.

---

## 1. Preparar o repositório no GitHub

O repositório **não pode conter** `.env`, `secure-connect-*.zip` nem `.streamlit/secrets.toml`. O `.gitignore` já os exclui; confirme antes do primeiro push:

```bash
git init
git add .
git status                      # confira a lista
git ls-files | grep -E "\.env$|secure-connect|secrets\.toml$"   # deve não mostrar nada
git commit -m "Mercado Livre: CLI e web"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/MercadoLivre.git
git push -u origin main
```

> **Se um segredo já foi enviado ao GitHub**, apagar o arquivo depois não basta (fica no histórico). Gere novas credenciais em cada serviço (senha do banco, token do Astra, senha do Aura) e invalide as antigas.

---

## 2. Criar os bancos gratuitos

| Serviço | Limites do plano gratuito (conferidos em 19/11/2026) | O que acontece com inatividade |
|---|---|---|
| **MongoDB Atlas M0** | 512 MB de armazenamento, até 500 conexões, 100 operações/s | Cluster gratuito pode ser pausado após longo período sem uso (cerca de 30 dias na documentação atual); retome no painel |
| **Redis Cloud (Free)** | 30 MB, 30 conexões, 100 ops/s | A base pode ser removida após cerca de 14 dias sem atividade; os dados do Redis aqui são só sessões/cache |
| **Astra DB (free plan)** | Créditos mensais gratuitos; sem cartão para começar | **Hiberna após 48 h sem uso** e pode ser removido se ficar hibernado; ao esgotar créditos o banco é suspenso |
| **Neo4j AuraDB Free** | 200 mil nós e 400 mil relacionamentos, 1 instância | **Pausa após 72 h sem uso**; excluída após 30 dias pausada |

A aplicação limita seus pools de conexão (padrão 10 por banco) para caber nesses limites; ajuste com `MONGODB_MAX_POOL`, `REDIS_MAX_CONNECTIONS` e `NEO4J_MAX_POOL` se precisar.

### 2.1 MongoDB Atlas

1. Crie um cluster **M0 (Free)**.
2. *Database Access* → crie um usuário **com permissão apenas `readWrite` no banco `mercadolivre`**.
3. *Network Access*: o Streamlit Community Cloud não tem IPs fixos, então é preciso permitir `0.0.0.0/0`. Isso expõe a porta do cluster a qualquer IP; a proteção passa a ser a senha forte do usuário. Use uma senha longa e aleatória.
4. *Connect → Drivers* e copie a *connection string* (vira `MONGODB_URI`).

### 2.2 Redis Cloud

1. Crie uma base **Free**, em região próxima da dos outros serviços.
2. Copie *host*, *porta* e *senha* (viram `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`). Se o painel indicar TLS, use `REDIS_SSL = "true"`.

### 2.3 Astra DB (Cassandra)

1. Crie um banco *Serverless* e um **keyspace** chamado `mercadolivre` (a aplicação cria as tabelas, mas não o keyspace).
2. Gere um **token** de aplicação com permissão para criar tabelas (por exemplo, *Database Administrator*) → `ASTRA_DB_TOKEN`.
3. Baixe o **Secure Connect Bundle** (`secure-connect-<nome>.zip`).
4. Converta o bundle para base64, pois o Streamlit Cloud não aceita upload de arquivos:

   ```bash
   # Linux
   base64 -w0 secure-connect-mercadolivre.zip
   # macOS
   base64 -i secure-connect-mercadolivre.zip
   ```
   ```powershell
   # Windows (copia para a área de transferência)
   [Convert]::ToBase64String([IO.File]::ReadAllBytes("secure-connect-mercadolivre.zip")) | Set-Clipboard
   ```

   O texto resultante é o valor de `ASTRA_SCB_B64`. Ele é um segredo: trate como senha.

### 2.4 Neo4j AuraDB

1. Crie uma instância **AuraDB Free** e **guarde a senha mostrada uma única vez** (o arquivo `.txt` de credenciais não deve ir para o GitHub).
2. Copie a URI (`neo4j+s://...`) → `NEO4J_URI`; usuário `neo4j` → `NEO4J_USERNAME`; senha → `NEO4J_PASSWORD`.

---

## 3. Contas da aplicação web

A web tem seu próprio login (separado dos bancos). Gere um hash para cada senha:

```bash
python -m web.auth.senhas
# Senha (não aparece na tela): ********
# pbkdf2_sha256$600000$....$....
```

Use senhas com pelo menos 10 caracteres. O hash é o que vai nos Secrets; a senha em si nunca é guardada.

- Papel `admin`: gerencia tudo.
- Papel `usuario`: consulta e compra **em seu próprio nome**. O `email` da conta deve ser igual ao e-mail do comprador cadastrado no MongoDB (é assim que a conta é ligada ao cadastro).

---

## 4. Publicar no Streamlit Community Cloud

1. Acesse <https://share.streamlit.io> e entre com o GitHub (autorize o acesso ao repositório).
2. **Create app** → *Deploy a public app from GitHub*.
3. Preencha:
   - **Repository:** `SEU_USUARIO/MercadoLivre`
   - **Branch:** `main`
   - **Main file path:** `web/app.py`
4. Abra **Advanced settings**:
   - **Python version:** escolha **3.12** (a versão em que o projeto foi testado; o `cassandra-driver 3.30.1` tem pacotes prontos para 3.11 a 3.14, então não são necessárias dependências de sistema, mas só a 3.12 foi exercitada).
   - **Secrets:** cole o conteúdo preenchido de [`.streamlit/secrets.toml.example`](../.streamlit/secrets.toml.example).
5. **Deploy**. A primeira instalação das dependências leva alguns minutos.

Os Secrets de primeiro nível (`MONGODB_URI`, `NEO4J_PASSWORD`...) são copiados para variáveis de ambiente na inicialização, sem sobrescrever as que já existirem. As contas ficam na tabela `[[auth.usuarios]]`.

### Configurações importantes

| Chave | Efeito |
|---|---|
| `APP_ENV = "production"` | Padrão. Nenhuma conta de demonstração existe. **Nunca use `development` em produção.** |
| `DEMO_MODE = "true"` | Visitantes navegam em somente leitura, com CPF/e-mail mascarados. Com `"false"`, tudo exige login. |
| `WEB_SESSION_TTL` | Duração da sessão de login em segundos (padrão 1800), renovada a cada ação. |

---

## 5. Primeira execução

1. Entre como `admin` na barra lateral.
2. **Diagnóstico**: os quatro bancos devem aparecer como *ONLINE*. Se algum falhar, veja a seção de problemas abaixo.
3. **Produtos → Carregar dados de demonstração (MongoDB)**.
4. **Histórico de compras → Modelagem → Carregar dados de demonstração (Cassandra)** e **Grafo → Carregar dados de demonstração (Neo4j)** (o botão fica no fim da página).
5. Cadastre o e-mail de cada conta `usuario` como comprador (página **Usuários**) para ela poder fazer pedidos.
6. Abra a URL em uma aba anônima para conferir a visão de visitante.

---

## 6. Limitações da hospedagem gratuita

- **Suspensão por inatividade (Streamlit):** segundo a documentação, o app entra em repouso após cerca de 12 horas sem tráfego e volta quando alguém o abre (alguns segundos de espera).
- **Recursos:** a plataforma limita memória e CPU por app (a documentação cita cerca de 2,7 GB de memória como teto). O app usa pouco; o maior consumo é o HTML do grafo (~700 KB por visualização).
- **Hibernação dos bancos:** Astra (48 h) e Aura (72 h) hibernam sozinhos. Para uma demonstração, **abra-os no painel do provedor no dia anterior** e depois use **Diagnóstico → Reiniciar conexões** (admin). Enquanto estiverem fora, a aplicação continua de pé e mostra *indisponível* só nas partes afetadas.
- **Rede:** o Streamlit Cloud sai por IPs variáveis, por isso o MongoDB Atlas precisa aceitar `0.0.0.0/0` (veja 2.1).
- **Latência:** o app roda nos EUA; escolha regiões de banco próximas (por exemplo, `us-east`) para reduzir o tempo de resposta.
- **Dados:** o plano gratuito não oferece backup automático adequado; trate o ambiente como demonstração.
- **Sessões em memória:** se o Redis cair, o login continua funcionando com armazenamento em memória do processo (as sessões se perdem a cada reinício do app).

---

## 7. Problemas comuns

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| Diagnóstico: MongoDB *FALHA* | IP não liberado ou senha com caracteres especiais | Libere `0.0.0.0/0`; codifique a senha na URI (`@` → `%40`) |
| Redis *FALHA*, mas login funciona | Redis fora do ar; o login usa memória | Confira host/porta/senha e `REDIS_SSL` |
| Cassandra *NÃO CONFIGURADO* | Falta `ASTRA_DB_TOKEN` ou `ASTRA_SCB_B64` | Confira os dois Secrets |
| Cassandra *FALHA* | Banco hibernado, token sem permissão ou keyspace inexistente | Retome no painel; crie o keyspace `mercadolivre`; reinicie as conexões |
| Neo4j *FALHA* | Instância pausada | Retome no painel do Aura; reinicie as conexões |
| "Nenhuma conta configurada" na barra lateral | `[[auth.usuarios]]` ausente ou com hash inválido | Gere o hash com `python -m web.auth.senhas` |
| Usuário não consegue comprar | O e-mail da conta não existe como comprador | Cadastre o comprador com o mesmo e-mail |
| Erro ao instalar o `cassandra-driver` | Versão de Python não suportada | Escolha Python 3.12 em *Advanced settings* |

Os logs do app (botão **Manage app**) mostram o detalhe técnico das falhas; os segredos configurados são removidos das mensagens antes de serem registradas.

---

## 8. Checklist antes de divulgar a URL

- [ ] `git ls-files` não lista `.env`, `secure-connect*` nem `secrets.toml`.
- [ ] `APP_ENV` é `production` (ou ausente).
- [ ] Senhas dos bancos e do admin são longas e únicas; o usuário do MongoDB só tem `readWrite` no banco da aplicação.
- [ ] Em uma aba anônima: não há CPF/e-mail completos visíveis, nenhum botão de escrita, e as páginas de Usuários e Pedidos pedem login.
- [ ] Diagnóstico mostra os quatro bancos *ONLINE*.
- [ ] Se algum serviço gratuito hibernou, ele foi retomado antes da apresentação.

## Se algo deixar de ser gratuito

A arquitetura não depende de um provedor específico: cada banco é acessado por variáveis de ambiente padrão (URIs e tokens). Se uma camada gratuita acabar, troque apenas as credenciais por outro serviço compatível (outro cluster MongoDB ou Redis, um Cassandra/Astra em outro plano, outro Neo4j). Para a hospedagem do app, qualquer serviço que execute `streamlit run web/app.py` e aceite variáveis de ambiente serve; as alternativas não foram avaliadas aqui, então verifique os limites atuais antes de migrar.
