
# Padrões SQL (Restaurantes)

Este documento define convenções de escrita SQL para consultas analíticas sobre o esquema de restaurante.  
Os padrões garantem consistência, clareza e performance, e orientam a geração automática de queries.

## Filtros de Período (padrão temporal)

Regra padrão (se o usuário não especificar):
```sql
WHERE sls.created_at >= NOW() - INTERVAL '90 days'
```

Variações comuns:
```sql
-- Últimos 30 dias
WHERE sls.created_at >= NOW() - INTERVAL '30 days'

-- Últimos 7 dias
WHERE sls.created_at >= NOW() - INTERVAL '7 days'

-- Mês atual (MTD)
WHERE DATE_TRUNC('month', sls.created_at) = DATE_TRUNC('month', NOW())

-- Mês anterior
WHERE sls.created_at BETWEEN DATE_TRUNC('month', NOW()) - INTERVAL '1 month'
                         AND DATE_TRUNC('month', NOW()) - INTERVAL '1 day'
```

Dica de performance:
- Prefira ranges de timestamp no WHERE em vez de `DATE(sls.created_at)`, para aproveitar os índices de `created_at`.

---

## Status de Venda

Filtro padrão:
```sql
WHERE sls.sale_status_desc = 'COMPLETED'
```

- Status possíveis: `COMPLETED`, `CANCELLED`
- Use ambos explicitamente quando houver comparação entre status.

---

## CTE Base (recomendado)

Sempre inicie consultas com uma CTE aplicando filtros de período e status antes de realizar joins.

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

- Evite `SELECT sls.*` — selecione apenas as colunas necessárias.

---

## Agregação Temporal (granularidades)

Use derivadas consistentes para garantir clareza e evitar duplicidade de lógica:

- Dia: `DATE_TRUNC('day', sls.created_at)` → `sale_date`
- Semana (ISO): `DATE_TRUNC('week', sls.created_at)` → `sale_week`
- Mês: `DATE_TRUNC('month', sls.created_at)` → `sale_month`
- Dia da semana: `EXTRACT(DOW FROM sls.created_at)` → `dow`
- Hora: `EXTRACT(HOUR FROM sls.created_at)` → `hour`

Exemplo:
```sql
SELECT
  DATE_TRUNC('day', bse.created_at) AS sale_date,
  COUNT(DISTINCT bse.id) AS sales_count
FROM base bse
GROUP BY 1
ORDER BY 1;
```

---

## Métricas Típicas (canônicas)

- Faturamento total: `SUM(sls.total_amount)`
- Valor pago: `SUM(sls.value_paid)`
- Descontos: `SUM(sls.total_discount)`
- Pedidos: `COUNT(DISTINCT sls.id)`
- Ticket médio: `SUM(sls.total_amount) / NULLIF(COUNT(DISTINCT sls.id), 0)`
- Unidades por produto: `SUM(prs.quantity)`
- Receita por produto: `SUM(prs.total_price)`
- SLA de entrega (P50/P90): `PERCENTILE_CONT(0.5/0.9) WITHIN GROUP (ORDER BY sls.delivery_seconds)`

Atenção:
- Diferencie receita por venda (`sales.total_amount`) de receita por produto (`product_sales.total_price`).

---

## Padrões de Join (por contexto)

Faturamento / Ticket / Pedidos
```sql
FROM base bse
JOIN stores str   ON str.id = bse.store_id
JOIN channels chn ON chn.id = bse.channel_id
LEFT JOIN customers cst ON cst.id = bse.customer_id
```

Top produtos
```sql
FROM product_sales prs
JOIN base bse   ON bse.id = prs.sale_id
JOIN products prd ON prd.id = prs.product_id
```

SLA (Delivery)
```sql
FROM base bse
JOIN channels chn ON chn.id = bse.channel_id
WHERE chn.type = 'D'
```

Pagamentos (Mix)
```sql
FROM base bse
LEFT JOIN payments pmt     ON pmt.sale_id = bse.id
LEFT JOIN payment_types ptp ON ptp.id = pmt.payment_type_id
```

---

## Boas Práticas

- Use CTEs para modular consultas.
- Sempre filtre `sale_status_desc` e `created_at` antes de qualquer join.
- Prefira `DATE_TRUNC()` para agregações temporais.
- Agregue fatos granulares (`product_sales`, `item_product_sales`) antes de unir com `sales`.
- Utilize `LEFT JOIN` para dimensões opcionais (`customers`, `payments`, `delivery_*`).
- Evite `SELECT *`.
- Use `ORDER BY ... LIMIT N` em consultas Top-N.
- Nomeie colunas derivadas com aliases consistentes (`sale_date`, `avg_ticket`, etc.).
- Utilize aliases/prefixos com no mínimo 3 letras e evite palavras reservadas.

---

## Exemplo Completo (Agregação diária por canal)

```sql
WITH base AS (
  SELECT
    sls.id,
    sls.store_id,
    sls.channel_id,
    sls.total_amount,
    sls.created_at
  FROM sales sls
  WHERE sls.sale_status_desc = 'COMPLETED'
    AND sls.created_at >= NOW() - INTERVAL '90 days'
)
SELECT
  DATE_TRUNC('day', bse.created_at) AS sale_date,
  chn.name AS channel_name,
  COUNT(DISTINCT bse.id) AS sales_count,
  SUM(bse.total_amount) AS total_amount,
  ROUND(SUM(bse.total_amount)/NULLIF(COUNT(DISTINCT bse.id), 0), 2) AS avg_ticket
FROM base bse
JOIN channels chn ON chn.id = bse.channel_id
GROUP BY 1, 2
ORDER BY 1, 2;
```

---

## Objetivo dos Padrões

Estes padrões garantem que:
1. As queries sejam consistentes e legíveis.
2. Os índices sejam utilizados de forma eficiente.
3. As métricas e agregações tenham significado uniforme em todo o domínio.
4. O RAG possa gerar SQL de alta qualidade e evitar erros clássicos de cardinalidade.
