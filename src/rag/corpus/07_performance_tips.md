
# Performance e Boas Práticas (versão revisada com aliases ≥3 letras)

Este guia reúne recomendações para escrever consultas SQL performáticas, legíveis e consistentes sobre o esquema de restaurantes.  
As diretrizes foram ampliadas para evitar erros comuns como joins cruzados, CTEs ineficientes e uso incorreto de aliases.

---

## 1) Filtros de Período e Uso de Índices
- Sempre aplique filtros de tempo e status o mais cedo possível (idealmente na CTE base).
- Use predicados por range, para aproveitar índices:
  ```sql
  sls.created_at >= NOW() - INTERVAL '90 days'
  ```
- Evite funções sobre colunas no WHERE:
  - ❌ `WHERE DATE(sls.created_at) >= ...`
  - ✅ `WHERE sls.created_at >= ...`
- Benefício: aproveita índices compostos como `idx_sales_date_status ON sales(created_at, sale_status_desc)`.

---

## 2) Projeção Eficiente (SELECT enxuto)
- Evite `SELECT *`.
- Inclua somente as colunas realmente necessárias para a análise ou joins subsequentes.
- Vantagens:
  - Menor I/O e uso de memória.
  - Reduz risco de conflitos de nomes (por exemplo, `id` em múltiplas tabelas).

---

## 3) CTEs: Clareza, Ordem e Reuso
- Estruture consultas com CTEs nomeadas claramente (`base_sales`, `product_revenue`, `customer_metrics`, etc.).
- Cada CTE deve ter um propósito único e finito — evitar sobreposição (ex.: duas CTEs filtrando o mesmo conjunto de vendas).
- Exemplo base padrão:
  ```sql
  WITH base_sales AS (
    SELECT
      sls.id,
      sls.store_id,
      sls.channel_id,
      sls.created_at,
      sls.total_amount
    FROM sales sls
    WHERE sls.sale_status_desc = 'COMPLETED'
      AND sls.created_at >= NOW() - INTERVAL '90 days'
  )
  ```
- Evite `ORDER BY` e `LIMIT` dentro da CTE, exceto em casos de ranking com `ROW_NUMBER()` — eles não garantem ordenação global.
- Nunca use vírgula entre CTEs no FROM (implica CROSS JOIN). Faça JOINs explícitos e finalize com `SELECT ... FROM <última CTE>`.

---

## 4) Controle de Cardinalidade em Joins
- Cuidado ao cruzar fatos:
  - `sales 1—N product_sales`
  - `product_sales 1—N item_product_sales`
- Regra de ouro:
  - Agregue primeiro na granularidade menor, depois junte.
  - Exemplo:
    ```sql
    WITH product_agg AS (
      SELECT sale_id, SUM(total_price) AS total_product_amount
      FROM product_sales
      GROUP BY sale_id
    )
    SELECT ...
    FROM sales sls
    JOIN product_agg pag ON pag.sale_id = sls.id;
    ```
- ❌ Errado: `sales JOIN product_sales JOIN item_product_sales` e depois agregar.
- ✅ Certo: agregar em `product_sales` e/ou `item_product_sales` primeiro.

---

## 5) LEFT JOIN para Dimensões Opcionais
- Use `LEFT JOIN` quando a ausência de dados não deve remover linhas do lado principal.
- Exemplo:
  ```sql
  sales sls
  LEFT JOIN customers cst ON cst.id = sls.customer_id
  LEFT JOIN payments pmt  ON pmt.sale_id = sls.id
  ```
- Evite `INNER JOIN` nesses casos — podem eliminar vendas legítimas sem cliente ou pagamento registrado.

---

## 6) Agregações Temporais Consistentes
- Padronize os cortes de tempo:
  - Dia → `DATE_TRUNC('day', sls.created_at)`
  - Semana → `DATE_TRUNC('week', sls.created_at)`
  - Mês → `DATE_TRUNC('month', sls.created_at)`
- Evite `DATE(sls.created_at)` — menos performático e inconsistente.
- Defina um padrão de granularidade e mantenha-o coeso em GROUP BYs e joins.

---

## 7) Construção de Rankings e Top-N
- Em rankings (Top-N), use:
  - `ORDER BY <métrica> DESC`
  - `LIMIT N` ao final do SELECT principal (não dentro da CTE).
- Para Top-N por grupo, use window functions:
  ```sql
  ROW_NUMBER() OVER (PARTITION BY store_id ORDER BY SUM(total_amount) DESC)
  ```
- Erros a evitar:
  - `ORDER BY` + `LIMIT` dentro da CTE → comportamento imprevisível.
  - Misturar CTEs sem JOIN explícito → gera CROSS JOIN (explosão combinatória).

---

## 8) Nomenclatura de Aliases e Prefixos (mínimo 3 letras)
- Use aliases curtos, claros e com no mínimo 3 letras.
- Nunca use palavras reservadas (ex.: `is`, `on`, `in`, `to`, etc.).
- Prefixos recomendados (≥ 3 letras):
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
- Exemplos:
  - ✅ `ips` (item_product_sales), `prs` (product_sales), `sls` (sales)
  - ❌ `is`, `ps`, `s` (curtos demais ou reservados)

---

## 9) Boas Práticas para Combinar CTEs
- Combine CTEs com JOIN em vez de usar vírgulas.
- Só use `CROSS JOIN` explicitamente quando realmente quiser combinar todos os registros.
- Exemplo ruim:
  ```sql
  FROM store_sales sts, item_sales itms
  ```
  → Gera CROSS JOIN entre todas as lojas e todos os itens.
- Exemplo bom:
  ```sql
  FROM store_sales sts
  JOIN stores str ON str.id = sts.store_id
  JOIN item_sales itms ON itms.store_id = str.id
  ```

---

## 10) Métricas Canônicas e Definições
- Receita por venda: `SUM(sls.total_amount)` — tabela `sales`.
- Receita por produto: `SUM(prs.total_price)` — tabela `product_sales`.
- Pedidos: `COUNT(DISTINCT sls.id)`.
- Ticket médio: `SUM(sls.total_amount) / NULLIF(COUNT(DISTINCT sls.id), 0)`.
- SLA de entrega: percentis de `sls.delivery_seconds` (apenas `chn.type='D'`).

---

## 11) Materializações e Caches
- Para relatórios de alta frequência:
  - Crie views materializadas com atualização agendada.
- Benefícios:
  - Diminui reprocessamento.
  - Melhora tempo de resposta em dashboards.

---

## 12) Sanity Checks e Qualidade
- Valide sempre a coerência das métricas:
  - `SUM(pmt.value)` ≈ `sls.value_paid`.
  - Contagem de entregas: `delivery_addresses` ≈ `delivery_sales`.
- Verifique tipos e integridade:
  - `prd.category_id → categories.type='P'`
  - `itm.category_id → categories.type='I'`

---

## Checklist Final Para Query Builder / RAG
- Filtre período e status cedo (na CTE base).
- Use apenas colunas necessárias.
- Evite funções no WHERE.
- Não use ORDER BY / LIMIT dentro de CTE sem motivo técnico.
- Use aliases seguros (evite palavras reservadas) e prefixos com no mínimo 3 letras.
- Agregue dados antes de joins.
- Use LEFT JOIN em dimensões opcionais.
- Evite vírgulas entre tabelas — sempre JOIN explícito.
- Nomeie CTEs e colunas com clareza e coerência.
---
