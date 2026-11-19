# Guia de apresentação: um projeto, quatro bancos

## A ideia em uma frase

> É um mini Mercado Livre. Os **mesmos dados** (usuários, lojas, produtos e compras) são guardados em **quatro bancos diferentes**, cada um usado no que faz de melhor.

Cada banco tem **um arquivo só**, então dá para abrir e explicar um de cada vez:

| Banco | Tipo | Arquivo | Pergunta que ele responde bem |
|---|---|---|---|
| MongoDB | documentos | `catalogo.py` | "Me dê este produto inteiro, com seus dados flexíveis" |
| Redis | chave-valor | `sessoes.py` | "Este usuário está logado? Por quanto tempo ainda?" |
| Cassandra | colunas | `historico.py` | "Quais as últimas compras deste usuário?" (muito volume) |
| Neo4j | grafos | `grafo.py` | "Quem comprou este produto e de qual loja?" (ligações) |

## Preparação (2 minutos antes)

1. `py -m mercadolivre.diagnostico` → as 4 linhas devem aparecer **ONLINE**.
2. Em cada módulo, rode **Carregar dados de demonstração** (MongoDB, Cassandra e Neo4j). Todos recebem os mesmos 2 usuários, 2 lojas e 4 produtos.
3. Abra o menu com `py -m mercadolivre`. Ao entrar em cada módulo aparece um quadro curto explicando o banco: pode ler direto dele.

## Como explicar cada banco

### 1. MongoDB: "uma gaveta de fichas"

- **Em uma frase:** guarda *documentos* (parecidos com JSON) em *coleções*; cada documento pode ter campos diferentes.
- **Analogia:** uma pasta com fichas de papel. Cada ficha tem tudo sobre uma coisa, inclusive listas (o usuário guarda seus endereços **dentro** da ficha dele).
- **Mostrar (menu "Catálogo e pedidos"):**
  1. *Usuários → Cadastrar* e *Listar* (insert e find).
  2. *Usuários → Atualizar* (update só do que mudou) e *Excluir* (delete).
  3. *Produtos → Buscar por título* (find com regex) e *Pedidos → Criar pedido* (estoque cai sozinho).
- **No código (`catalogo.py`):** `cadastrar_usuario` (`insert_one`), `atualizar_usuario` (`update_one` com `$set`), `buscar_produtos` (`$regex`), `_produtos_com_vendedor` (`$lookup`, o "JOIN"), `criar_pedido` (baixa atômica de estoque).
- **Pergunta provável:** *"Por que não SQL?"* → O produto tem campos que variam e o endereço vive dentro do usuário; no MongoDB isso é um documento só, sem várias tabelas.

### 2. Redis: "um post-it que some sozinho"

- **Em uma frase:** guarda pares *chave → valor* na **memória**, por isso é muito rápido, e cada chave pode ter prazo de validade.
- **Analogia:** o crachá de visitante que perde a validade depois de 60 segundos.
- **Mostrar (menu "Sessões e cache"):**
  1. *Login* (`aluno@fatec.sp.gov.br` / `senha123`) e depois *Acompanhar sessão ao vivo*: a barra desce até a sessão expirar.
  2. Errar a senha 5 vezes: o login é bloqueado (contador também expira).
  3. *Executar fluxo MongoDB → Redis → MongoDB*: 2 produtos saem do Mongo, passam por CRUD no Redis e voltam. (Rode antes a demonstração do MongoDB para existirem produtos.)
- **No código (`sessoes.py`):** `login` (`SET ... EX`), `checar_sessao` (`EXPIRE` renova o prazo, `TTL` mostra o que resta), `login` (`INCR` conta falhas), `fluxo_itens` (CRUD: `SET`, `GET`, `DEL`), `devolver_ao_mongo`.
- **Pergunta provável:** *"E se o Redis cair?"* → Por ser memória, ele serve para dados temporários (sessão, cache). O dado de verdade fica no MongoDB, por isso o fluxo devolve os itens para lá.

### 3. Cassandra: "uma tabela para cada pergunta"

- **Em uma frase:** parece SQL (CQL), mas **não tem JOIN**; cada tabela é desenhada para uma consulta, e o mesmo dado pode ficar em duas tabelas.
- **Analogia:** em vez de procurar numa lista só, você mantém duas listas prontas: "compras por número" e "compras por cliente, da mais nova para a mais antiga".
- **Mostrar (menu "Histórico de compras"):**
  1. *Compras → Registrar* e *Listar por usuário*: já vem em ordem de data, sem `ORDER BY`.
  2. *Compras → Excluir*: apaga das duas tabelas juntas.
  3. *Produtos → Testar consulta sem chave de partição*: o Cassandra **recusa**. Esse é o ponto mais didático.
- **No código (`historico.py`):** `DDL` (as 6 tabelas e suas chaves), `inserir_compra` (grava em `compra` e `compra_por_usuario` num batch), `listar_compras`, `consulta_sem_chave`.
- **Chaves, simples:** *partition key* = em qual nó o dado mora; *clustering key* = a ordem dentro dele.
- **Pergunta provável:** *"Não é desperdício guardar duas vezes?"* → Sim, de propósito: espaço é barato, consulta lenta em escala não é.

### 4. Neo4j: "um mapa de ligações"

- **Em uma frase:** guarda *nós* (coisas) e *relacionamentos* (setas entre elas); consultar é caminhar pelas setas.
- **Analogia:** um mapa mental: Fulano → comprou → Mouse → vendido por → Mundo Periférico.
- **Mostrar (menu "Grafo de compras"):**
  1. *Explorar o grafo → Compras de um usuário (árvore)*: Usuário → Compra → Produto → Loja.
  2. *Explorar o grafo → Quem comprou um produto*: o caminho ao contrário.
  3. *Resumo*: quantos nós e relacionamentos existem. No painel do Aura (Query), rode `MATCH (n)-[r]->(m) RETURN n, r, m` para **ver o desenho**.
- **No código (`grafo.py`):** `SCHEMA` (restrições), `inserir_produto` e `inserir_compra` (`MERGE` e `CREATE` de nós e setas), `buscar_compras` (o `MATCH` que percorre as setas).
- **Pergunta provável:** *"Qual a diferença para o MongoDB, que também tem `$lookup`?"* → No Mongo a ligação é um id copiado que você precisa juntar; no Neo4j a ligação já existe e atravessá-la é a consulta.

## O mesmo dado, quatro formas

Uma compra do "Mouse Sem Fio":

- **MongoDB:** um documento em `pedidos`, com a lista de itens dentro.
- **Redis:** não guarda a compra; guarda a *sessão* de quem comprou (`session:<email>`).
- **Cassandra:** duas linhas, uma em `compra` e outra em `compra_por_usuario`.
- **Neo4j:** um nó `Compra` ligado por setas ao `Usuario` e ao `Produto`.

## Apresentando pela web

`APP_ENV=development streamlit run web/app.py` (ou a URL publicada, veja [DEPLOY.md](DEPLOY.md)). Cada banco tem a sua página:

- **Produtos / Pedidos** (MongoDB): crie um pedido e veja o estoque cair sozinho.
- **Sessões e cache** (Redis): *Criar sessão de demonstração* e acompanhe a barra do TTL descer até o Redis apagar a chave.
- **Histórico de compras** (Cassandra): aba *Modelagem*, que mostra a tabela de cada consulta.
- **Grafo** (Neo4j): arraste os nós; a seta `REALIZOU` liga o usuário à compra e `DE_PRODUTO` liga a compra ao produto.
- **Diagnóstico**: derrube um banco (ou deixe um sem credencial) e mostre que o resto do sistema continua de pé.

## Fechamento (frase pronta)

> "Não existe banco melhor, existe banco certo para cada problema: **Mongo** para dados flexíveis, **Redis** para o que é rápido e temporário, **Cassandra** para muito volume com consultas conhecidas e **Neo4j** para o que importa são as ligações."
