
# Relacionamentos e Joins Canônicos

Este documento define as cardinalidades, chaves/foreign keys e os joins SQL canônicos do esquema de restaurante. O objetivo é garantir consultas consistentes, evitar duplicação de linhas e facilitar a geração automática de SQL.

## Visão Geral de Cardinalidades
- brands 1—N sub_brands, channels, payment_types, categories, products, items, stores
- sub_brands 1—N stores, products, items
- categories (type='P') 1—N products
- categories (type='I') 1—N items
- stores 1—N sales
- channels 1—N sales
- customers 1—N sales  (opcional: venda pode não ter cliente)
- sales 1—N product_sales
- product_sales 1—N item_product_sales
- products 1—N product_sales
- items N—N product_sales (via item_product_sales)
- option_groups 1—N item_product_sales (opcional)
- sales 1—N payments
- payment_types 1—N payments
- sales 1—0/1 delivery_sales
- delivery_sales 1—1 delivery_addresses

## Chaves e FKs (resumo)
- sub_brands.brand_id → brands.id
- channels.brand_id → brands.id
- payment_types.brand_id → brands.id
- categories.brand_id → brands.id
- products.(brand_id, sub_brand_id, category_id) → brands.id, sub_brands.id, categories.id
- items.(brand_id, sub_brand_id, category_id) → brands.id, sub_brands.id, categories.id
- stores.(brand_id, sub_brand_id) → brands.id, sub_brands.id
- sales.(store_id, channel_id, customer_id?) → stores.id, channels.id, customers.id (opcional)
- product_sales.(sale_id, product_id) → sales.id, products.id
- item_product_sales.(product_sale_id, item_id, option_group_id?) → product_sales.id, items.id, option_groups.id (opcional)
- delivery_sales.sale_id → sales.id
- delivery_addresses.(delivery_sale_id, sale_id) → delivery_sales.id, sales.id
- payments.(sale_id, payment_type_id) → sales.id, payment_types.id

## Joins Canônicos (SQL)
Use sempre `sales` como fato central e aplique filtros de período/status antes dos joins.

- sales.store_id = stores.id
- sales.channel_id = channels.id
- sales.customer_id = customers.id                -- usar LEFT JOIN
- product_sales.sale_id = sales.id
- item_product_sales.product_sale_id = product_sales.id
- payments.sale_id = sales.id
- payments.payment_type_id = payment_types.id
- products.id = product_sales.product_id
- categories.id = products.category_id
- delivery_sales.sale_id = sales.id
- delivery_addresses.delivery_sale_id = delivery_sales.id
- delivery_addresses.sale_id = sales.id           -- redundante, útil para sanity check

## Padrões de Join por Caso de Uso (com exemplos)

### 1) Visão de vendas por loja/canal (sem duplicar linhas)
```sql
WITH base AS (
  SELECT s.id, s.store_id, s.channel_id, s.created_at, s.total_amount
  FROM sales s
  WHERE s.sale_status_desc = 'COMPLETED'
    AND s.created_at >= NOW() - INTERVAL '90 days'
)
SELECT
  st.name AS store_name,
  c.name  AS channel_name,
  COUNT(DISTINCT b.id) AS sales_count,
  SUM(b.total_amount)  AS total_amount
FROM base b
JOIN stores   st ON st.id = b.store_id
JOIN channels c  ON c.id = b.channel_id
GROUP BY 1,2;
```

Por que: evita multiplicação de linhas mantendo apenas dimensões de `sales`.

### 2) Receita/unidades por produto (subindo granularidade de product_sales para sales)
```sql
WITH base AS (
  SELECT s.id, s.created_at
  FROM sales s
  WHERE s.sale_status_desc = 'COMPLETED'
    AND s.created_at >= NOW() - INTERVAL '90 days'
),
prod AS (
  SELECT
    ps.sale_id,
    ps.product_id,
    SUM(ps.quantity)    AS units,
    SUM(ps.total_price) AS product_revenue
  FROM product_sales ps
  JOIN base b ON b.id = ps.sale_id
  GROUP BY 1,2
)
SELECT
  p.name,
  SUM(prod.units)           AS units,
  SUM(prod.product_revenue) AS revenue
FROM prod
JOIN products p ON p.id = prod.product_id
GROUP BY 1
ORDER BY revenue DESC;
```

Por que: agregamos em `product_sales` antes de juntar com outras dimensões para não multiplicar linhas.

### 3) Complementos/itens por grupo de opção
```sql
WITH base AS (
  SELECT s.id
  FROM sales s
  WHERE s.sale_status_desc = 'COMPLETED'
    AND s.created_at >= NOW() - INTERVAL '90 days'
),
items_agg AS (
  SELECT
    ips.product_sale_id,
    og.id   AS option_group_id,
    og.name AS option_group_name,
    SUM(ips.quantity) AS units,
    SUM(ips.amount)   AS amount
  FROM item_product_sales ips
  JOIN product_sales ps ON ps.id = ips.product_sale_id
  JOIN base b          ON b.id = ps.sale_id
  LEFT JOIN option_groups og ON og.id = ips.option_group_id
  GROUP BY 1,2,3
)
SELECT option_group_name, SUM(units) AS units, SUM(amount) AS amount
FROM items_agg
GROUP BY 1
ORDER BY amount DESC;
```

Por que: a agregação em `item_product_sales` evita duplicidades quando cruzada com `product_sales` e além.

### 4) Mix de pagamentos por tipo
```sql
WITH base AS (
  SELECT s.id
  FROM sales s
  WHERE s.sale_status_desc = 'COMPLETED'
    AND s.created_at >= NOW() - INTERVAL '90 days'
)
SELECT
  pt.description AS payment_type,
  SUM(pay.value) AS paid_value
FROM base b
LEFT JOIN payments pay     ON pay.sale_id = b.id
LEFT JOIN payment_types pt ON pt.id = pay.payment_type_id
GROUP BY 1
ORDER BY paid_value DESC;
```

Por que: pagamentos são 1—N por venda; `LEFT JOIN` preserva vendas sem pagamento registrado (dados incompletos).

### 5) Métricas de entrega (apenas canais Delivery)
```sql
WITH base AS (
  SELECT s.id, s.channel_id, s.delivery_seconds
  FROM sales s
  WHERE s.sale_status_desc = 'COMPLETED'
    AND s.created_at >= NOW() - INTERVAL '90 days'
)
SELECT
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY b.delivery_seconds) AS p50_delivery_s,
  PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY b.delivery_seconds) AS p90_delivery_s
FROM base b
JOIN channels c ON c.id = b.channel_id
WHERE c.type = 'D';
```

Por que: restringe a canais de entrega, garantindo semântica correta da métrica.

## Antipadrões e Como Evitar

- Cross de fatos sem agregação:
  - Errado: `sales JOIN product_sales JOIN item_product_sales` e depois somar `total_amount` → multiplica linhas.
  - Certo: agregue em `product_sales` e/ou `item_product_sales` primeiro, depois suba a granularidade para `sale_id`.

- Filtro temporal com função no campo:
  - Errado: `WHERE DATE(s.created_at) >= DATE(NOW()) - 90` (pode invalidar índice).
  - Certo: `WHERE s.created_at >= NOW() - INTERVAL '90 days'`.

- INNER JOIN em dimensões opcionais:
  - Errado: `sales JOIN customers` (perde vendas sem cliente).
  - Certo: `sales LEFT JOIN customers`.

- Usar `SELECT *`:
  - Evite; selecione apenas as colunas necessárias para reduzir I/O e risco de ambiguidade.

## Sanity Checks de Relacionamento
- `COUNT(DISTINCT delivery_addresses.sale_id)` deve ser próximo de `COUNT(DISTINCT delivery_sales.sale_id)` para vendas de `channels.type='D'`.
- `SUM(payments.value)` por `sale_id` deve aproximar `sales.value_paid` (diferenças por troco/ajustes).
- `products.category_id` deve referenciar `categories.type='P'`; `items.category_id` → `type='I'`.
