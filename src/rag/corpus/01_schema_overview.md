
# Visão Geral do Esquema (Restaurante)

Este documento resume entidades, relações, regras de negócio e diretrizes de performance para relatórios de operação e vendas no domínio de restaurantes. Ele serve como referência para geração automática de SQL (via LLM) e para analistas humanos.

## Escopo e Finalidade
- Público-alvo: geração de SQL por LLM e analistas de dados.
- Objetivo: padronizar joins, filtros, métricas e índices para respostas consistentes e rápidas.
- Banco de dados: PostgreSQL.

## Principais Entidades
- Dimensões de marca/canal/produto:
  - brands, sub_brands, channels, payment_types, categories, products, items, option_groups
- Dimensões de loja e cliente:
  - stores, customers
- Fatos de vendas e entregas:
  - sales, product_sales, item_product_sales
  - delivery_sales, delivery_addresses
  - payments

## Regras de Negócio (Essenciais)
- Status de venda: `sales.sale_status_desc ∈ {COMPLETED, CANCELLED}`
  - Default analítico: considerar apenas `COMPLETED`, salvo instrução em contrário.
- Tipo de canal: `channels.type ∈ {'P' (Presencial), 'D' (Delivery)}`
  - Delivery habilita joins com `delivery_sales` e `delivery_addresses`.
- Tipo de categoria: `categories.type ∈ {'P' (Produtos), 'I' (Itens)}`
  - `products` devem referenciar categorias `type='P'`; `items` devem referenciar `type='I'`.
- Grão (granularidade):
  - `sales`: 1 linha por venda/pedido.
  - `product_sales`: 1 linha por produto dentro de uma venda.
  - `item_product_sales`: 1 linha por item/opção dentro de um produto vendido.

## Tabelas Fato (Grãos e Colunas-Chave)
- sales (grão: 1 por venda)
  - Colunas-chave: `id`, `store_id`, `channel_id`, `customer_id`, `created_at`, `sale_status_desc`
  - Valores: `total_amount`, `total_discount`, `delivery_fee`, `service_tax_fee`, `value_paid`
  - Tempos: `production_seconds`, `delivery_seconds`
- product_sales (grão: 1 por produto por venda)
  - Colunas-chave: `id`, `sale_id`, `product_id`
  - Métricas: `quantity`, `base_price`, `total_price`
- item_product_sales (grão: 1 por item/opção no produto da venda)
  - Colunas-chave: `product_sale_id`, `item_id`, `option_group_id` (opcional)
  - Métricas: `quantity`, `price`, `additional_price`, `amount`

Observação: agregações por “produto” usam `product_sales`; agregações por “item/complemento” usam `item_product_sales`.

## Relacionamentos e Joins Canônicos
- Hierarquias de marca:
  - `brands 1—N sub_brands, channels, payment_types, categories, products, items, stores`
  - `sub_brands 1—N stores, products, items`
- Catálogos:
  - `categories(type='P') 1—N products`
  - `categories(type='I') 1—N items`
- Vendas:
  - `stores 1—N sales`
  - `channels 1—N sales`
  - `customers 1—N sales` (opcional → usar LEFT JOIN quando necessário)
  - `sales 1—N product_sales`
  - `product_sales 1—N item_product_sales`
  - `products 1—N product_sales`
  - `items N—N product_sales` (via `item_product_sales`)
- Entregas e pagamentos:
  - `sales 1—0/1 delivery_sales`
  - `delivery_sales 1—1 delivery_addresses`
  - `sales 1—N payments`
  - `payment_types 1—N payments`

Joins comuns:
- `sales.store_id = stores.id`
- `sales.channel_id = channels.id`
- `sales.customer_id = customers.id` (LEFT)
- `product_sales.sale_id = sales.id`
- `item_product_sales.product_sale_id = product_sales.id`
- `payments.sale_id = sales.id` e `payments.payment_type_id = payment_types.id`
- `products.id = product_sales.product_id`
- `categories.id = products.category_id`
- `delivery_sales.sale_id = sales.id`
- `delivery_addresses.delivery_sale_id = delivery_sales.id`

Diretriz: evite multiplicação de linhas ao juntar `sales` com `product_sales` e `item_product_sales` simultaneamente; agregue por nível antes de juntar quando precisar subir granularidade.

## Padrões de Filtro e Tempo
- Janela padrão (fallback): últimos 90 dias
  - Prefira predicados por range para aproveitar índices:
    `sls.created_at >= NOW() - INTERVAL '90 days'`
- Status padrão: `sls.sale_status_desc = 'COMPLETED'`
- Derivações temporais (para SELECT/GROUP BY):
  - Dia: `DATE_TRUNC('day', sls.created_at)` → `sale_date`
  - Semana ISO: `DATE_TRUNC('week', sls.created_at)` → `sale_week`
  - Mês: `DATE_TRUNC('month', sls.created_at)` → `sale_month`
  - Dia da semana: `EXTRACT(DOW FROM sls.created_at)` (0=domingo) → `dow`
  - Hora: `EXTRACT(HOUR FROM sls.created_at)` → `hour`

## Métricas Canônicas (Definições Base)
- Faturamento por venda: `SUM(sls.total_amount)`
- Pedidos (contagem de vendas): `COUNT(DISTINCT sls.id)`
- Ticket médio: `SUM(sls.total_amount)/NULLIF(COUNT(DISTINCT sls.id),0)`
- Receita por produto: `SUM(prs.total_price)`
- Unidades por produto: `SUM(prs.quantity)`
- SLA de entrega (percentis):
  `PERCENTILE_CONT(0.5/0.9) WITHIN GROUP (ORDER BY sls.delivery_seconds)`

Observação: diferencie claramente “receita por venda” (`sales.total_amount`) de “receita por produto” (`product_sales.total_price`) nas análises e rótulos.

## Diretrizes de Performance
- Índices-chave existentes:
  - `idx_sales_date_status ON sales(created_at, sale_status_desc)`
    - Observação: use ranges em `created_at` no WHERE (evite `DATE(sls.created_at)` no predicado) para o plano usar o índice.
  - `idx_product_sales_product_sale ON product_sales(product_id, sale_id)`
- Índices recomendados (avaliar conforme carga/consultas):
  - `sales(channel_id, created_at, sale_status_desc)`
  - `sales(store_id, created_at, sale_status_desc)`
  - `product_sales(sale_id)` INCLUDE (`product_id`, `quantity`, `total_price`)
- Boas práticas:
  - Sempre filtrar período e status na CTE base.
  - Selecionar apenas colunas necessárias (evitar `SELECT *`).
  - Usar `LEFT JOIN` para dimensões opcionais (clientes, pagamentos, delivery_*).
  - Para Top-N, use `ORDER BY ... LIMIT N`.
  - Considere views materializadas para agregações diárias ou janelas deslizantes comuns.

## Snippet Padrão (CTE base)
Use este snippet como base para queries analíticas:

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

## Aliases e Prefixos (mínimo 3 letras)
- Use aliases com no mínimo 3 letras, claros e estáveis.
- Nunca use palavras reservadas como alias (ex.: `is`, `on`, `in`, `to`).
- Prefixos recomendados:
  - `sls` → `sales`
  - `prs` → `product_sales`
  - `ips` → `item_product_sales`
  - `str` → `stores`
  - `chn` → `channels`
  - `cst` → `customers`
  - `pmt` → `payments`
  - `ptp` → `payment_types`
  - `prd` → `products`
  - `itm` → `items`
  - `cat` → `categories`
  - `brd` → `brands`
  - `sbd` → `sub_brands`

## Sanity Checks (Recomendações)
- `SUM(pmt.value)` por `sale_id` deve se aproximar de `sls.value_paid` (diferenças podem ocorrer por troco/descontos).
- `prd.category_id` deve apontar para `categories.type='P'`; `itm.category_id` para `type='I'`.
- Nem toda venda `chn.type='D'` terá `delivery_sales/delivery_addresses` em dados incompletos; use `LEFT JOIN`.
