
# Exemplos de Queries

Este documento reúne padrões de consultas prontas, seguindo as diretrizes de filtros, joins e métricas definidas nos arquivos anteriores. Todas as queries:
- Filtram `sale_status_desc = 'COMPLETED'`.
- Usam janelas temporais com predicados por range para aproveitar índices.
- Evitam multiplicação de linhas ao lidar com fatos granulares.

## 1) Vendas por canal por dia (8 semanas) com ticket médio
Objetivo: volume de vendas, faturamento e ticket médio por canal e dia nos últimos 56 dias.

```sql
WITH base AS (
  SELECT s.id, s.created_at, s.total_amount, s.sale_status_desc, s.channel_id
  FROM sales s
  WHERE s.created_at >= NOW() - INTERVAL '56 days'
    AND s.sale_status_desc = 'COMPLETED'
)
SELECT
  DATE_TRUNC('day', b.created_at) AS sale_date,
  c.name AS channel_name,
  COUNT(DISTINCT b.id) AS sales_count,
  SUM(b.total_amount) AS total_amount,
  ROUND(SUM(b.total_amount) / NULLIF(COUNT(DISTINCT b.id),0), 2) AS avg_ticket
FROM base b
JOIN channels c ON c.id = b.channel_id
GROUP BY 1,2
ORDER BY 1,2;
```

Notas:
- `DATE_TRUNC('day', ...)` é preferível a `DATE(...)` para consistência com outros grãos temporais.
- Se desejar apenas delivery/presencial, adicione `WHERE c.type IN ('D')` ou `('P')`.

## 2) Top 10 produtos por receita (90 dias)
Objetivo: ranquear produtos por receita total (somatório de `product_sales.total_price`).

```sql
WITH base AS (
  SELECT s.id
  FROM sales s
  WHERE s.created_at >= NOW() - INTERVAL '90 days'
    AND s.sale_status_desc = 'COMPLETED'
),
prod AS (
  SELECT ps.product_id, SUM(ps.total_price) AS revenue
  FROM product_sales ps
  JOIN base b ON b.id = ps.sale_id
  GROUP BY ps.product_id
)
SELECT p.name, pr.revenue
FROM prod pr
JOIN products p ON p.id = pr.product_id
ORDER BY pr.revenue DESC
LIMIT 10;
```

Notas:
- A agregação é feita em `product_sales` antes de juntar a `products` para evitar duplicidades.
- Para filtrar por sub_brand, inclua join com `products.sub_brand_id` ou `brands`.

## 3) Faturamento por loja e cidade (30 dias)
Objetivo: faturamento e contagem de pedidos por loja e cidade.

```sql
WITH base AS (
  SELECT s.id, s.store_id, s.total_amount, s.delivery_fee, s.service_tax_fee, s.created_at
  FROM sales s
  WHERE s.created_at >= NOW() - INTERVAL '30 days'
    AND s.sale_status_desc = 'COMPLETED'
)
SELECT
  st.name AS store_name,
  st.city,
  COUNT(DISTINCT b.id) AS sales_count,
  SUM(b.total_amount) AS total_amount,
  SUM(b.delivery_fee) AS total_delivery_fee,
  SUM(b.service_tax_fee) AS total_service_tax
FROM base b
JOIN stores st ON st.id = b.store_id
GROUP BY 1,2
ORDER BY total_amount DESC;
```

Notas:
- Se preferir consolidar por UF, substitua `st.city` por `st.state`.
- Para excluir lojas inativas: adicione `WHERE st.is_active IS TRUE`.

## 4) Mix de pagamentos por tipo (últimos 60 dias)
Objetivo: composição do valor pago por tipo de pagamento.

```sql
WITH base AS (
  SELECT s.id
  FROM sales s
  WHERE s.created_at >= NOW() - INTERVAL '60 days'
    AND s.sale_status_desc = 'COMPLETED'
)
SELECT
  pt.description AS payment_type,
  SUM(p.value)   AS paid_value
FROM base b
LEFT JOIN payments p      ON p.sale_id = b.id
LEFT JOIN payment_types pt ON pt.id = p.payment_type_id
GROUP BY 1
ORDER BY paid_value DESC;
```

Notas:
- `LEFT JOIN` preserva vendas mesmo se houver divergência/ausência de lançamento em `payments`.
- Para participação percentual por tipo, divida por o total geral com uma window function.

## 5) SLA de entrega (P50/P90) por canal (90 dias, somente Delivery)
Objetivo: percentis de tempo de entrega por canal de delivery.

```sql
WITH base AS (
  SELECT s.id, s.channel_id, s.delivery_seconds
  FROM sales s
  WHERE s.created_at >= NOW() - INTERVAL '90 days'
    AND s.sale_status_desc = 'COMPLETED'
)
SELECT
  c.name AS channel_name,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY b.delivery_seconds) AS p50_delivery_s,
  PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY b.delivery_seconds) AS p90_delivery_s
FROM base b
JOIN channels c ON c.id = b.channel_id
WHERE c.type = 'D'
GROUP BY 1
ORDER BY p50_delivery_s;
```

Notas:
- Garanta que `delivery_seconds` não contenha nulos ou outliers extremos conforme regra do negócio.

## 6) Top 10 itens/complementos por receita (90 dias)
Objetivo: ranquear itens de `item_product_sales` por receita, considerando grupos de opção.

```sql
WITH base AS (
  SELECT s.id
  FROM sales s
  WHERE s.created_at >= NOW() - INTERVAL '90 days'
    AND s.sale_status_desc = 'COMPLETED'
),
items_agg AS (
  SELECT
    ips.item_id,
    COALESCE(og.name, 'Sem grupo') AS option_group_name,
    SUM(ips.quantity) AS units,
    SUM(ips.amount)   AS amount
  FROM item_product_sales ips
  JOIN product_sales ps ON ps.id = ips.product_sale_id
  JOIN base b          ON b.id = ps.sale_id
  LEFT JOIN option_groups og ON og.id = ips.option_group_id
  GROUP BY 1,2
)
SELECT i.name AS item_name, option_group_name, units, amount
FROM items_agg ia
JOIN items i ON i.id = ia.item_id
ORDER BY amount DESC
LIMIT 10;
```

Notas:
- A agregação em `item_product_sales` evita multiplicar linhas quando cruzada com outras dimensões.
- Útil para entender upsell de complementos.

## 7) Recorrência de clientes (120 dias)
Objetivo: classificar clientes por frequência de compras.

```sql
WITH base AS (
  SELECT s.id, s.customer_id
  FROM sales s
  WHERE s.created_at >= NOW() - INTERVAL '120 days'
    AND s.sale_status_desc = 'COMPLETED'
    AND s.customer_id IS NOT NULL
)
SELECT
  CASE
    WHEN cnt = 1 THEN 'Novos'
    WHEN cnt BETWEEN 2 AND 4 THEN 'Recorrentes (2-4)'
    ELSE 'Alta recorrência (5+)'
  END AS cohort,
  COUNT(*) AS customers
FROM (
  SELECT customer_id, COUNT(*) AS cnt
  FROM base
  GROUP BY customer_id
) t
GROUP BY 1
ORDER BY 1;
```

Notas:
- `LEFT JOIN customers` pode ser adicionado para atributos (e-mail, origem etc.), mantendo privacidade.

## 8) Curva ABC de produtos (90 dias)
Objetivo: classificar produtos em A/B/C com base na participação na receita.

```sql
WITH base AS (
  SELECT s.id
  FROM sales s
  WHERE s.created_at >= NOW() - INTERVAL '90 days'
    AND s.sale_status_desc = 'COMPLETED'
),
prod AS (
  SELECT ps.product_id, SUM(ps.total_price) AS revenue
  FROM product_sales ps
  JOIN base b ON b.id = ps.sale_id
  GROUP BY ps.product_id
),
ranked AS (
  SELECT
    p.product_id,
    p.revenue,
    RANK() OVER (ORDER BY p.revenue DESC) AS rnk,
    SUM(p.revenue) OVER () AS total_rev,
    SUM(p.revenue) OVER (ORDER BY p.revenue DESC) AS cum_rev
  FROM prod p
),
scored AS (
  SELECT
    product_id,
    revenue,
    cum_rev / NULLIF(total_rev,0) AS cum_share
  FROM ranked
)
SELECT
  prd.name,
  s.revenue,
  CASE
    WHEN s.cum_share <= 0.8 THEN 'A'
    WHEN s.cum_share <= 0.95 THEN 'B'
    ELSE 'C'
  END AS abc_class
FROM scored s
JOIN products prd ON prd.id = s.product_id
ORDER BY s.revenue DESC;
```

Notas:
- Limiares A/B/C podem ser ajustados conforme política (ex.: 70/90).

---
