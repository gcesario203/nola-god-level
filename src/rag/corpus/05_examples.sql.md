
# Exemplos de Queries

Todas as queries:
- Filtram `sale_status_desc = 'COMPLETED'`.
- Usam predicados por range no tempo para aproveitar índices.
- Evitam multiplicação de linhas agregando fatos granulares antes dos joins.
- Usam aliases com no mínimo 3 letras.

## 1) Vendas por canal por dia (8 semanas) com ticket médio
Objetivo: volume de vendas, faturamento e ticket médio por canal e dia nos últimos 56 dias.

```sql
WITH base AS (
  SELECT sls.id, sls.created_at, sls.total_amount, sls.sale_status_desc, sls.channel_id
  FROM sales sls
  WHERE sls.created_at >= NOW() - INTERVAL '56 days'
    AND sls.sale_status_desc = 'COMPLETED'
)
SELECT
  DATE_TRUNC('day', bse.created_at) AS sale_date,
  chn.name AS channel_name,
  COUNT(DISTINCT bse.id) AS sales_count,
  SUM(bse.total_amount) AS total_amount,
  ROUND(SUM(bse.total_amount) / NULLIF(COUNT(DISTINCT bse.id), 0), 2) AS avg_ticket
FROM base bse
JOIN channels chn ON chn.id = bse.channel_id
GROUP BY 1, 2
ORDER BY 1, 2;
```

## 2) Top 10 produtos por receita (90 dias)
```sql
WITH base AS (
  SELECT sls.id
  FROM sales sls
  WHERE sls.created_at >= NOW() - INTERVAL '90 days'
    AND sls.sale_status_desc = 'COMPLETED'
),
prod AS (
  SELECT prs.product_id, SUM(prs.total_price) AS revenue
  FROM product_sales prs
  JOIN base bse ON bse.id = prs.sale_id
  GROUP BY prs.product_id
)
SELECT prd.name, pr.revenue
FROM prod pr
JOIN products prd ON prd.id = pr.product_id
ORDER BY pr.revenue DESC
LIMIT 10;
```

## 3) Faturamento por loja e cidade (30 dias)
```sql
WITH base AS (
  SELECT sls.id, sls.store_id, sls.total_amount, sls.delivery_fee, sls.service_tax_fee, sls.created_at
  FROM sales sls
  WHERE sls.created_at >= NOW() - INTERVAL '30 days'
    AND sls.sale_status_desc = 'COMPLETED'
)
SELECT
  str.name AS store_name,
  str.city,
  COUNT(DISTINCT bse.id) AS sales_count,
  SUM(bse.total_amount) AS total_amount,
  SUM(bse.delivery_fee) AS total_delivery_fee,
  SUM(bse.service_tax_fee) AS total_service_tax
FROM base bse
JOIN stores str ON str.id = bse.store_id
GROUP BY 1, 2
ORDER BY total_amount DESC;
```

## 4) Mix de pagamentos por tipo (60 dias) com participação
```sql
WITH base AS (
  SELECT sls.id
  FROM sales sls
  WHERE sls.created_at >= NOW() - INTERVAL '60 days'
    AND sls.sale_status_desc = 'COMPLETED'
),
pay_mix AS (
  SELECT
    ptp.description AS payment_type,
    SUM(pmt.value)  AS paid_value
  FROM base bse
  LEFT JOIN payments pmt      ON pmt.sale_id = bse.id
  LEFT JOIN payment_types ptp ON ptp.id = pmt.payment_type_id
  GROUP BY 1
)
SELECT
  payment_type,
  paid_value,
  ROUND(100.0 * paid_value / NULLIF(SUM(paid_value) OVER (), 0), 2) AS pct_share
FROM pay_mix
ORDER BY paid_value DESC;
```

## 5) SLA de entrega (P50/P90) por canal (Delivery, 90 dias)
```sql
WITH base AS (
  SELECT sls.id, sls.channel_id, sls.delivery_seconds
  FROM sales sls
  WHERE sls.created_at >= NOW() - INTERVAL '90 days'
    AND sls.sale_status_desc = 'COMPLETED'
)
SELECT
  chn.name AS channel_name,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY bse.delivery_seconds) AS p50_delivery_s,
  PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY bse.delivery_seconds) AS p90_delivery_s
FROM base bse
JOIN channels chn ON chn.id = bse.channel_id
WHERE chn.type = 'D'
GROUP BY 1
ORDER BY p50_delivery_s;
```

## 6) Top 10 itens/complementos por receita (90 dias)
```sql
WITH base AS (
  SELECT sls.id
  FROM sales sls
  WHERE sls.created_at >= NOW() - INTERVAL '90 days'
    AND sls.sale_status_desc = 'COMPLETED'
),
items_agg AS (
  SELECT
    ips.item_id,
    COALESCE(ogr.name, 'Sem grupo') AS option_group_name,
    SUM(ips.quantity) AS units,
    SUM(ips.amount)   AS amount
  FROM item_product_sales ips
  JOIN product_sales prs ON prs.id = ips.product_sale_id
  JOIN base bse          ON bse.id = prs.sale_id
  LEFT JOIN option_groups ogr ON ogr.id = ips.option_group_id
  GROUP BY 1, 2
)
SELECT itm.name AS item_name, option_group_name, units, amount
FROM items_agg iag
JOIN items itm ON itm.id = iag.item_id
ORDER BY amount DESC
LIMIT 10;
```

## 7) Recorrência de clientes (120 dias)
```sql
WITH base AS (
  SELECT sls.id, sls.customer_id
  FROM sales sls
  WHERE sls.created_at >= NOW() - INTERVAL '120 days'
    AND sls.sale_status_desc = 'COMPLETED'
    AND sls.customer_id IS NOT NULL
),
counts AS (
  SELECT customer_id, COUNT(*) AS cnt
  FROM base
  GROUP BY customer_id
)
SELECT
  CASE
    WHEN cnt = 1 THEN 'Novos'
    WHEN cnt BETWEEN 2 AND 4 THEN 'Recorrentes (2-4)'
    ELSE 'Alta recorrência (5+)'
  END AS cohort,
  COUNT(*) AS customers
FROM counts
GROUP BY 1
ORDER BY 1;
```

## 8) Curva ABC de produtos (90 dias)
```sql
WITH base AS (
  SELECT sls.id
  FROM sales sls
  WHERE sls.created_at >= NOW() - INTERVAL '90 days'
    AND sls.sale_status_desc = 'COMPLETED'
),
prod AS (
  SELECT prs.product_id, SUM(prs.total_price) AS revenue
  FROM product_sales prs
  JOIN base bse ON bse.id = prs.sale_id
  GROUP BY prs.product_id
),
ranked AS (
  SELECT
    prd.product_id,
    prd.revenue,
    RANK() OVER (ORDER BY prd.revenue DESC) AS rnk,
    SUM(prd.revenue) OVER () AS total_rev,
    SUM(prd.revenue) OVER (ORDER BY prd.revenue DESC) AS cum_rev
  FROM prod prd
),
scored AS (
  SELECT
    product_id,
    revenue,
    cum_rev / NULLIF(total_rev, 0) AS cum_share
  FROM ranked
)
SELECT
  prd.name,
  sco.revenue,
  CASE
    WHEN sco.cum_share <= 0.8  THEN 'A'
    WHEN sco.cum_share <= 0.95 THEN 'B'
    ELSE 'C'
  END AS abc_class
FROM scored sco
JOIN products prd ON prd.id = sco.product_id
ORDER BY sco.revenue DESC;
```

## 9) Top-N por grupo: 3 produtos mais vendidos por loja (30 dias)
```sql
WITH base AS (
  SELECT sls.id, sls.store_id
  FROM sales sls
  WHERE sls.created_at >= NOW() - INTERVAL '30 days'
    AND sls.sale_status_desc = 'COMPLETED'
),
prod_store AS (
  SELECT
    prs.product_id,
    bse.store_id,
    SUM(prs.total_price) AS revenue
  FROM product_sales prs
  JOIN base bse ON bse.id = prs.sale_id
  GROUP BY 1, 2
),
ranked AS (
  SELECT
    prs.product_id,
    prs.store_id,
    prs.revenue,
    ROW_NUMBER() OVER (PARTITION BY prs.store_id ORDER BY prs.revenue DESC) AS rn
  FROM prod_store prs
)
SELECT
  str.name AS store_name,
  prd.name AS product_name,
  rnk.revenue
FROM ranked rnk
JOIN stores str   ON str.id = rnk.store_id
JOIN products prd ON prd.id = rnk.product_id
WHERE rnk.rn <= 3
ORDER BY str.name, rnk.revenue DESC;
```

## 10) Rolling 7d: vendas por dia com média móvel
```sql
WITH base AS (
  SELECT sls.id, sls.created_at, sls.total_amount
  FROM sales sls
  WHERE sls.created_at >= NOW() - INTERVAL '120 days'
    AND sls.sale_status_desc = 'COMPLETED'
),
daily AS (
  SELECT
    DATE_TRUNC('day', bse.created_at) AS sale_date,
    SUM(bse.total_amount) AS daily_amount
  FROM base bse
  GROUP BY 1
)
SELECT
  dly.sale_date,
  dly.daily_amount,
  AVG(dly.daily_amount) OVER (
    ORDER BY dly.sale_date
    ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
  ) AS ma7_amount
FROM daily dly
ORDER BY dly.sale_date;
```

## 11) Último preço efetivo por produto (Postgres DISTINCT ON)
```sql
WITH base AS (
  SELECT
    prs.product_id,
    sls.created_at,
    prs.total_price / NULLIF(prs.quantity, 0) AS unit_price
  FROM product_sales prs
  JOIN sales sls ON sls.id = prs.sale_id
  WHERE sls.sale_status_desc = 'COMPLETED'
    AND sls.created_at >= NOW() - INTERVAL '180 days'
)
SELECT DISTINCT ON (bse.product_id)
  bse.product_id,
  prd.name AS product_name,
  bse.unit_price,
  bse.created_at AS last_sold_at
FROM base bse
JOIN products prd ON prd.id = bse.product_id
ORDER BY bse.product_id, bse.created_at DESC;
```

## 12) Cohort mensal de retenção (primeira compra vs. retornos)
```sql
WITH base AS (
  SELECT sls.id, sls.customer_id, sls.created_at
  FROM sales sls
  WHERE sls.created_at >= NOW() - INTERVAL '365 days'
    AND sls.sale_status_desc = 'COMPLETED'
    AND sls.customer_id IS NOT NULL
),
first_purchase AS (
  SELECT
    bse.customer_id,
    DATE_TRUNC('month', MIN(bse.created_at)) AS cohort_month
  FROM base bse
  GROUP BY bse.customer_id
),
activity AS (
  SELECT
    bse.customer_id,
    DATE_TRUNC('month', bse.created_at) AS activity_month
  FROM base bse
)
SELECT
  fp.cohort_month,
  act.activity_month,
  COUNT(DISTINCT act.customer_id) AS active_customers
FROM first_purchase fp
JOIN activity act ON act.customer_id = fp.customer_id
GROUP BY 1, 2
ORDER BY 1, 2;
```

## 13) Normalização de canais (de-para textual)
```sql
WITH base AS (
  SELECT sls.id, sls.channel_id
  FROM sales sls
  WHERE sls.created_at >= NOW() - INTERVAL '90 days'
    AND sls.sale_status_desc = 'COMPLETED'
),
nm AS (
  SELECT
    chn.id,
    CASE
      WHEN LOWER(chn.name) IN ('ifood', 'i-food', 'i food') THEN 'iFood'
      WHEN LOWER(chn.name) IN ('app', 'application', 'mobile app') THEN 'App'
      ELSE chn.name
    END AS channel_norm
  FROM channels chn
)
SELECT
  nm.channel_norm,
  COUNT(DISTINCT bse.id) AS sales_count
FROM base bse
JOIN nm ON nm.id = bse.channel_id
GROUP BY 1
ORDER BY 2 DESC;
```

## 14) Basket analysis simples: co-ocorrência de produtos
Objetivo: pares de produtos que mais ocorrem juntos no mesmo pedido.

```sql
WITH base AS (
  SELECT sls.id
  FROM sales sls
  WHERE sls.created_at >= NOW() - INTERVAL '120 days'
    AND sls.sale_status_desc = 'COMPLETED'
),
pairs AS (
  SELECT
    LEAST(a.product_id, b.product_id)  AS product_id_a,
    GREATEST(a.product_id, b.product_id) AS product_id_b,
    COUNT(*) AS cnt_orders_together
  FROM product_sales a
  JOIN product_sales b
    ON a.sale_id = b.sale_id
   AND a.product_id < b.product_id
  JOIN base bse ON bse.id = a.sale_id
  GROUP BY 1, 2
)
SELECT
  prd_a.name AS product_a,
  prd_b.name AS product_b,
  cnt_orders_together
FROM pairs prs
JOIN products prd_a ON prd_a.id = prs.product_id_a
JOIN products prd_b ON prd_b.id = prs.product_id_b
ORDER BY cnt_orders_together DESC
LIMIT 50;
```

## 15) Funil de produção/entrega por hora do dia (Delivery, 30 dias)
```sql
WITH base AS (
  SELECT sls.id, sls.created_at, sls.delivery_seconds, sls.channel_id
  FROM sales sls
  WHERE sls.created_at >= NOW() - INTERVAL '30 days'
    AND sls.sale_status_desc = 'COMPLETED'
),
by_hour AS (
  SELECT
    EXTRACT(HOUR FROM bse.created_at)::int AS hour_of_day,
    COUNT(DISTINCT bse.id) AS sales_count,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY bse.delivery_seconds) AS p50_delivery_s,
    PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY bse.delivery_seconds) AS p90_delivery_s
  FROM base bse
  JOIN channels chn ON chn.id = bse.channel_id
  WHERE chn.type = 'D'
  GROUP BY 1
)
SELECT *
FROM by_hour
ORDER BY hour_of_day;
```

## 16) Comparativo YoY por mês (com calendário derivado)
```sql
WITH base AS (
  SELECT sls.id, sls.created_at, sls.total_amount
  FROM sales sls
  WHERE sls.created_at >= DATE_TRUNC('year', NOW()) - INTERVAL '1 year'
    AND sls.sale_status_desc = 'COMPLETED'
),
monthly AS (
  SELECT
    DATE_TRUNC('month', bse.created_at) AS month_dt,
    SUM(bse.total_amount) AS revenue
  FROM base bse
  GROUP BY 1
),
this_year AS (
  SELECT month_dt, revenue
  FROM monthly
  WHERE month_dt >= DATE_TRUNC('year', NOW())
),
last_year AS (
  SELECT month_dt + INTERVAL '1 year' AS month_dt, revenue AS revenue_ly
  FROM monthly
  WHERE month_dt < DATE_TRUNC('year', NOW())
)
SELECT
  ty.month_dt,
  ty.revenue AS revenue_ty,
  ly.revenue_ly,
  ROUND(100.0 * (ty.revenue - ly.revenue_ly) / NULLIF(ly.revenue_ly, 0), 2) AS yoy_pct
FROM this_year ty
LEFT JOIN last_year ly USING (month_dt)
ORDER BY ty.month_dt;
```
