
# Padrões SQL (Restaurantes)

Este documento define convenções de escrita SQL para consultas analíticas sobre o esquema de restaurante.  
Os padrões garantem consistência, clareza e performance, e orientam a geração automática de queries.

## Filtros de Período (padrão temporal)

**Regra padrão (se o usuário não especificar):**
```sql
WHERE s.created_at >= NOW() - INTERVAL '90 days'
```

**Variações comuns:**
```sql
-- Últimos 30 dias
WHERE s.created_at >= NOW() - INTERVAL '30 days'

-- Últimos 7 dias
WHERE s.created_at >= NOW() - INTERVAL '7 days'

-- Mês atual (MTD)
WHERE DATE_TRUNC('month', s.created_at) = DATE_TRUNC('month', NOW())

-- Mês anterior
WHERE s.created_at BETWEEN DATE_TRUNC('month', NOW()) - INTERVAL '1 month'
                      AND DATE_TRUNC('month', NOW()) - INTERVAL '1 day'
```

> 💡 **Dica de performance:**  
> Prefira ranges de `timestamp` no `WHERE` em vez de `DATE(s.created_at)`, para aproveitar os índices de `created_at`.

---

## Status de Venda

**Filtro padrão:**
```sql
WHERE s.sale_status_desc = 'COMPLETED'
```

- Status possíveis: `COMPLETED`, `CANCELLED`  
- Use ambos explicitamente quando houver comparação entre status.

---

## CTE Base (recomendado)

Sempre inicie consultas com uma CTE aplicando filtros de **período** e **status** antes de realizar joins.

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

> 🚫 Evite `SELECT s.*` — selecione apenas as colunas necessárias.

---

## Agregação Temporal (granularidades)

Use derivadas consistentes para garantir clareza e evitar duplicidade de lógica:

| Granularidade | Expressão SQL | Alias sugerido |
|----------------|---------------|----------------|
| Dia | `DATE_TRUNC('day', s.created_at)` | `sale_date` |
| Semana (ISO) | `DATE_TRUNC('week', s.created_at)` | `sale_week` |
| Mês | `DATE_TRUNC('month', s.created_at)` | `sale_month` |
| Dia da semana | `EXTRACT(DOW FROM s.created_at)` | `dow` |
| Hora | `EXTRACT(HOUR FROM s.created_at)` | `hour` |

**Exemplo:**
```sql
SELECT
  DATE_TRUNC('day', b.created_at) AS sale_date,
  COUNT(DISTINCT b.id) AS sales_count
FROM base b
GROUP BY 1
ORDER BY 1;
```

---

## Métricas Típicas (canônicas)

| Métrica | Descrição | Exemplo SQL |
|----------|------------|-------------|
| **Faturamento total** | Soma do valor bruto das vendas concluídas | `SUM(s.total_amount)` |
| **Valor pago** | Soma do valor efetivamente recebido | `SUM(s.value_paid)` |
| **Descontos** | Total de descontos aplicados | `SUM(s.total_discount)` |
| **Pedidos** | Número de vendas únicas | `COUNT(DISTINCT s.id)` |
| **Ticket médio** | Receita média por pedido | `SUM(s.total_amount)/NULLIF(COUNT(DISTINCT s.id),0)` |
| **Unidades por produto** | Quantidade total vendida | `SUM(ps.quantity)` |
| **Receita por produto** | Soma do total vendido em product_sales | `SUM(ps.total_price)` |
| **SLA de entrega (P50/P90)** | Percentis de tempo de entrega | `PERCENTILE_CONT(0.5/0.9) WITHIN GROUP (ORDER BY s.delivery_seconds)` |

> ⚠️ Diferencie **receita por venda** (`sales.total_amount`) de **receita por produto** (`product_sales.total_price`).

---

## Padrões de Join (por contexto)

**Faturamento / Ticket / Pedidos**
```sql
FROM base b
JOIN stores st   ON st.id = b.store_id
JOIN channels c  ON c.id = b.channel_id
LEFT JOIN customers cu ON cu.id = b.customer_id
```

**Top produtos**
```sql
FROM product_sales ps
JOIN base b   ON b.id = ps.sale_id
JOIN products p ON p.id = ps.product_id
```

**SLA (Delivery)**
```sql
FROM base b
JOIN channels c ON c.id = b.channel_id
WHERE c.type = 'D'
```

**Pagamentos (Mix)**
```sql
FROM base b
LEFT JOIN payments pay     ON pay.sale_id = b.id
LEFT JOIN payment_types pt ON pt.id = pay.payment_type_id
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

---

## Exemplo Completo (Agregação diária por canal)

```sql
WITH base AS (
  SELECT
    s.id,
    s.store_id,
    s.channel_id,
    s.total_amount,
    s.created_at
  FROM sales s
  WHERE s.sale_status_desc = 'COMPLETED'
    AND s.created_at >= NOW() - INTERVAL '90 days'
)
SELECT
  DATE_TRUNC('day', b.created_at) AS sale_date,
  c.name AS channel_name,
  COUNT(DISTINCT b.id) AS sales_count,
  SUM(b.total_amount) AS total_amount,
  ROUND(SUM(b.total_amount)/NULLIF(COUNT(DISTINCT b.id),0), 2) AS avg_ticket
FROM base b
JOIN channels c ON c.id = b.channel_id
GROUP BY 1,2
ORDER BY 1,2;
```

---

## Objetivo dos Padrões

Esses padrões garantem que:
1. As queries sejam consistentes e legíveis.  
2. Os índices sejam utilizados de forma eficiente.  
3. As métricas e agregações tenham significado uniforme em todo o domínio.  
4. O RAG possa gerar SQL de alta qualidade e evitar erros clássicos de cardinalidade.
