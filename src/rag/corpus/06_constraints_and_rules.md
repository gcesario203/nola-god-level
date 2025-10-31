
# Regras de Negócio (Restaurantes)

Este documento consolida as regras de negócio que orientam a geração de SQL e a interpretação de métricas no domínio de restaurantes. As regras servem como padrão quando o usuário não especificar alternativas.

## 1) Status de Venda
- Domínio: `sales.sale_status_desc ∈ {'COMPLETED', 'CANCELLED'}`
- Padrão analítico: considerar apenas `COMPLETED`, salvo instrução explícita em contrário.
- Implicações:
  - Métricas de receita, ticket médio, unidades e pagamentos devem usar vendas `COMPLETED`.
  - Para análises de cancelamentos, filtrar `CANCELLED` explicitamente (evite misturar com `COMPLETED`).

## 2) Janela Temporal Padrão
- Padrão (fallback): últimos 90 dias.
- Predicado recomendado (usa índice):
  - `sls.created_at >= NOW() - INTERVAL '90 days'`
- Evitar:
  - `WHERE DATE(sls.created_at) >= ...` (pode inviabilizar o uso do índice em `created_at`).

## 3) Canais de Venda
- Domínio: `channels.type ∈ {'P', 'D'}`
  - `'P'` = Presencial
  - `'D'` = Delivery
- Implicações:
  - Métricas de entrega (ex.: `delivery_seconds`) só fazem sentido para `type='D'`.
  - Para análises exclusivas de delivery ou presencial, adicionar filtro por `channels.type`.

## 4) Entrega e Endereços
- Presença condicional:
  - `delivery_sales` e `delivery_addresses` existem somente quando:
    - o canal é de entrega (`channels.type='D'`), e
    - a venda foi concluída (`sales.sale_status_desc='COMPLETED'`) — sujeito à disponibilidade de dados.
- Joins recomendados:
  - `sales (LEFT) → delivery_sales (LEFT) → delivery_addresses`
- Sanity check:
  - `COUNT(DISTINCT delivery_addresses.sale_id)` ≈ `COUNT(DISTINCT delivery_sales.sale_id)` nas vendas de delivery.

## 5) Origem do Pedido (`sales.origin`)
- Valor comum: `'POS'` (pedido originado no ponto de venda).
- Outros valores possíveis (dependem da integração): `'APP'`, `'AGGREGATOR'`, `'WEB'`, etc.
- Uso:
  - Filtrar ou segmentar análises por `origin` quando necessário (ex.: performance do PDV vs. app).

## 6) Granularidade de Fatos
- `sales`: 1 linha por venda/pedido.
- `product_sales`: 1 linha por produto dentro da venda.
- `item_product_sales`: 1 linha por item/complemento vinculado ao produto da venda.
- Regra geral:
  - Agregue fatos granulares (produto/itens) antes de unir com `sales` para evitar multiplicação de linhas.

## 7) Métricas Canônicas (referência)
- Receita por venda: `SUM(sls.total_amount)` em `sales`.
- Receita por produto: `SUM(prs.total_price)` em `product_sales`.
- Pedidos: `COUNT(DISTINCT sls.id)`.
- Ticket médio: `SUM(sls.total_amount) / NULLIF(COUNT(DISTINCT sls.id), 0)`.
- SLA de entrega: percentis em `sls.delivery_seconds` para `channels.type='D'`.

## 8) Padrões de Filtro e CTE Base
- Sempre aplicar:
  - Filtro de período + status antes dos joins.
- Snippet base sugerido:
  ```sql
  WITH base AS (
    SELECT
      sls.id,
      sls.store_id,
      sls.channel_id,
      sls.customer_id,
      sls.created_at,
      sls.sale_status_desc,
      sls.total_amount,
      sls.value_paid,
      sls.total_discount,
      sls.delivery_seconds
    FROM sales sls
    WHERE sls.sale_status_desc = 'COMPLETED'
      AND sls.created_at >= NOW() - INTERVAL '90 days'
  )
  ```
- Benefícios:
  - Menos dados em memória, uso de índices, joins mais rápidos e menor risco de duplicidade.

## 9) Privacidade e Dados Pessoais (LGPD)
- Restringir uso/exibição de dados pessoais (`customers.email`, `cpf`, `phone_number`) ao mínimo necessário.
- Preferir agregações e contagens em vez de listagens sensíveis.
- Quando possível, mascarar/anonimizar dados em relatórios operacionais.

## 10) Boas Práticas Operacionais
- Evitar `SELECT *`; selecionar apenas colunas necessárias.
- Em dimensões opcionais (`customers`, `payments`, `delivery_*`), preferir `LEFT JOIN`.
- Para consultas Top-N, usar `ORDER BY ... LIMIT N`.
- Considerar materializações (views materializadas) para agregações diárias frequentes.
- Usar aliases/prefixos com no mínimo 3 letras e evitar palavras reservadas.
