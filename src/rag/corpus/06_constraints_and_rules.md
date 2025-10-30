
# Regras de Negócio (Restaurantes)

Este documento consolida as regras de negócio que devem orientar a geração de SQL e a interpretação de métricas no domínio de restaurantes. As regras aqui definidas servem como padrão quando o usuário não especificar alternativas.

## 1) Status de Venda
- Domínio: `sales.sale_status_desc ∈ {'COMPLETED', 'CANCELLED'}`
- Padrão analítico: considerar apenas `COMPLETED`, salvo instrução explícita em contrário.
- Implicações:
  - Métricas de receita, ticket médio, unidades e pagamentos devem usar vendas `COMPLETED`.
  - Para análises de cancelamentos, filtrar `CANCELLED` explicitamente (evite misturar com `COMPLETED`).

## 2) Janela Temporal Padrão
- Padrão (fallback): últimos 90 dias.
- Predicado recomendado (usa índice):
  - `s.created_at >= NOW() - INTERVAL '90 days'`
- Evitar:
  - `WHERE DATE(s.created_at) >= ...` (pode inviabilizar o uso do índice em `created_at`).

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

## 5) Origem do Pedido (sales.origin)
- Valor comum: `'POS'` (pedido originado no ponto de venda).
- Outros valores possíveis (dependem da integração): `'APP'`, `'AGGREGATOR'`, `'WEB'`, etc.
- Uso:
  - Filtrar ou segmentar análises por `origin` quando necessário (ex.: performance do PDV vs app).

## 6) Granularidade de Fatos
- `sales`: 1 linha por venda/pedido.
- `product_sales`: 1 linha por produto dentro da venda.
- `item_product_sales`: 1 linha por item/complemento vinculado ao produto da venda.
- Regra geral:
  - Agregue fatos granulares (produto/itens) antes de unir com `sales` para evitar multiplicação de linhas.

## 7) Métricas Canônicas (referência)
- Receita por venda: `SUM(s.total_amount)` em `sales`.
- Receita por produto: `SUM(ps.total_price)` em `product_sales`.
- Pedidos: `COUNT(DISTINCT s.id)`.
- Ticket médio: `SUM(s.total_amount) / NULLIF(COUNT(DISTINCT s.id), 0)`.
- SLA de entrega: percentis em `s.delivery_seconds` para `channels.type='D'`.

## 8) Padrões de Filtro e CTE Base
- Sempre aplicar:
  - Filtro de período + status antes dos joins.
- Snippet base sugerido:
  ```sql
  WITH base AS (
    SELECT
      s.id,
      s.store_id,
      s.channel_id,
      s.customer_id,
      s.created_at,
      s.sale_status_desc,
      s.total_amount,
      s.value_paid,
      s.total_discount,
      s.delivery_seconds
    FROM sales s
    WHERE s.sale_status_desc = 'COMPLETED'
      AND s.created_at >= NOW() - INTERVAL '90 days'
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
- Em dimensões opcionais (clientes, payments, delivery_*), preferir `LEFT JOIN`.
- Para consultas Top-N, usar `ORDER BY ... LIMIT N`.
- Considerar materializações (views materializadas) para agregações diárias frequentes.
