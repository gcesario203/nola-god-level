
# Performance e Boas Práticas

Este guia reúne recomendações para escrever consultas SQL performáticas e consistentes sobre o esquema de restaurantes. As diretrizes abaixo ajudam a evitar planos ruins, duplicação de linhas e leituras desnecessárias.

## 1) Filtros de Período e Uso de Índices
- Sempre aplique filtros temporais cedo (na CTE base) para reduzir o volume de dados.
- Use predicados por range para permitir o uso de índices, por exemplo:
  - `s.created_at >= NOW() - INTERVAL '90 days'`
- Evite funções no campo do filtro temporal no WHERE:
  - Errado: `WHERE DATE(s.created_at) >= ...`
  - Certo: `WHERE s.created_at >= ...`
- Benefício: aproveita índices como `idx_sales_date_status ON sales(created_at, sale_status_desc)`.

## 2) Selecione Apenas o Necessário
- Evite `SELECT *`; liste apenas colunas necessárias.
- Vantagens:
  - Menos I/O e memória.
  - Menor risco de colisão de nomes e ambiguidades ao fazer joins.

## 3) Prefira CTEs para Clareza e Reuso
- Use uma CTE base para consolidar filtros padrão (período + status).
- Exemplo de snippet:
  ```sql
  WITH base AS (
    SELECT
      s.id,
      s.store_id,
      s.channel_id,
      s.customer_id,
      s.created_at,
      s.sale_status_desc,
      s.total_amount
    FROM sales s
    WHERE s.sale_status_desc = 'COMPLETED'
      AND s.created_at >= NOW() - INTERVAL '90 days'
  )
  ```
- Benefícios:
  - Menos repetição de filtros.
  - Joins mais previsíveis e fáceis de revisar.

## 4) Controle de Cardinalidade em Joins
- Atenção especial ao cruzar fatos:
  - `sales 1—N product_sales`
  - `product_sales 1—N item_product_sales`
- Regra de ouro: agregue no nível granular antes de “subir” a granularidade.
  - Ex.: agregue `product_sales` por `sale_id` (ou `product_id`) antes de juntar com `sales`.
- Evite fazer `sales JOIN product_sales JOIN item_product_sales` e somar valores de `sales` na mesma consulta sem agregações intermediárias.

## 5) LEFT JOIN para Dimensões Opcionais
- Use `LEFT JOIN` quando o lado principal não deve perder linhas:
  - Ex.: manter todas as vendas mesmo sem `customers`, `payments` ou `delivery_*`.
- Exemplos:
  - `sales LEFT JOIN customers ON customers.id = sales.customer_id`
  - `sales LEFT JOIN payments ON payments.sale_id = sales.id`

## 6) Agregações Temporais Consistentes
- Padronize granularidades temporais:
  - Dia: `DATE_TRUNC('day', s.created_at) AS sale_date`
  - Semana ISO: `DATE_TRUNC('week', s.created_at) AS sale_week`
  - Mês: `DATE_TRUNC('month', s.created_at) AS sale_month`
- Evite `DATE(...)` no WHERE; no SELECT/ GROUP BY é aceitável, mas prefira `DATE_TRUNC` para consistência.

## 7) Top-N e Exploração
- Em consultas de ranking (Top-N), sempre finalize com:
  - `ORDER BY <métrica> DESC`
  - `LIMIT N`
- Em conjuntos muito grandes, considere filtros adicionais (por período, marca, sub-brand, loja).

## 8) Métricas Canônicas e Definições
- Receita por venda: `SUM(s.total_amount)` (tabela `sales`).
- Receita por produto: `SUM(ps.total_price)` (tabela `product_sales`).
- Pedidos: `COUNT(DISTINCT s.id)`.
- Ticket médio: `SUM(s.total_amount) / NULLIF(COUNT(DISTINCT s.id), 0)`.
- SLA de entrega: percentis de `delivery_seconds` somente para `channels.type='D'`.

## 9) Materializações e Caches
- Para relatórios diários ou janelas deslizantes muito usadas:
  - Considere views materializadas com refresh agendado.
- Benefícios: respostas mais rápidas e carga menor no banco.

## 10) Sanity Checks e Qualidade
- Verifique consistências:
  - `SUM(payments.value)` por `sale_id` ≈ `sales.value_paid`.
  - `delivery_addresses` ≈ `delivery_sales` para canais de delivery.
- Confirme mapeamentos de categoria:
  - `products.category_id → categories.type='P'`
  - `items.category_id → categories.type='I'`

---
