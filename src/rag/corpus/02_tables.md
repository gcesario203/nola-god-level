# Tabelas e Colunas

Este documento descreve colunas, chaves, propósito analítico e notas de uso para cada tabela. Serve como referência para geração de SQL consistente e performática.

## brands
- Chaves: id (PK)
- Colunas: id (PK), name (text)
- Propósito: Dimensão raiz que agrupa sub_marcas, lojas, catálogos e canais.
- Notas:
  - Útil para isolar escopos multi-brand.
  - Filtro por brand pode ser aplicado cedo para reduzir dados.

## sub_brands
- Chaves: id (PK), brand_id (FK → brands.id)
- Colunas: id, brand_id, name (text)
- Propósito: Segmenta uma marca em linhas de negócio (ex.: “Burgers”, “Pizzas”).
- Notas:
  - Boa dimensão para comparativos intra-brand.

## channels
- Chaves: id (PK), brand_id (FK → brands.id)
- Colunas: id, brand_id, name (text), description (text), type (char: 'P'|'D')
- Propósito: Origem dos pedidos (Presencial vs Delivery; iFood, Rappi, WhatsApp, etc.).
- Notas:
  - `type = 'P'` (presencial), `type = 'D'` (delivery).
  - Matching por nome/descritivo: `LOWER(name/description) LIKE '%...%'`.
  - Métricas de entrega (ex.: `delivery_seconds`) só fazem sentido para `type='D'`.

## payment_types
- Chaves: id (PK), brand_id (FK → brands.id)
- Colunas: id, brand_id, description (text)
- Propósito: Tipos de pagamento (cartão, dinheiro, PIX, etc.) para análise de mix.
- Notas:
  - Relacionar via `payments.payment_type_id`.

## categories
- Chaves: id (PK), brand_id (FK → brands.id)
- Colunas: id, brand_id, name (text), type (char: 'P'|'I')
- Propósito: Classifica produtos e itens.
- Notas:
  - type 'P' → `products`; type 'I' → `items` (complementos).
  - Evitar misturar métricas de produto com item.

## products
- Chaves: id (PK), brand_id (FK), sub_brand_id (FK), category_id (FK → categories.id)
- Colunas: id, brand_id, sub_brand_id, category_id, name (text), pos_uuid (text)
- Propósito: Catálogo de produtos principais do cardápio.
- Notas:
  - Receita por produto via `product_sales.total_price`.
  - `category_id` deve apontar para `categories.type='P'`.
  - `pos_uuid` pode auxiliar reconciliação com o PDV.

## items
- Chaves: id (PK), brand_id (FK), sub_brand_id (FK), category_id (FK → categories.id)
- Colunas: id, brand_id, sub_brand_id, category_id, name (text), pos_uuid (text)
- Propósito: Complementos/opcionais associados a produtos.
- Notas:
  - Métricas de itens estão em `item_product_sales`.
  - `category_id` deve apontar para `categories.type='I'`.

## option_groups
- Chaves: id (PK), brand_id (FK → brands.id)
- Colunas: id, brand_id, name (text)
- Propósito: Agrupa itens em conjuntos lógicos (ex.: “Pães”, “Queijos”, “Molhos”).
- Notas:
  - Campo opcional em `item_product_sales`.

## stores
- Chaves: id (PK), brand_id (FK), sub_brand_id (FK)
- Colunas: id, brand_id, sub_brand_id, name (text),
          city (text), state (text), district (text),
          address_street (text), address_number (text),
          latitude (numeric), longitude (numeric),
          is_active (bool), is_own (bool),
          creation_date (date), created_at (timestamp)
- Propósito: Unidade operacional de venda.
- Notas:
  - Dimensão-chave para análises por loja e geográficas.
  - `is_active` pode excluir lojas desativadas em relatórios operacionais.

## customers
- Chaves: id (PK)
- Colunas: id, customer_name (text), email (text), phone_number (text),
          cpf (text), birth_date (date), gender (text),
          agree_terms (bool), receive_promotions_email (bool),
          registration_origin (text), created_at (timestamp)
- Propósito: Base de clientes para análises de recorrência, churn e segmentação.
- Notas:
  - Em joins com `sales`, use `LEFT JOIN` (cliente pode ser nulo).
  - Atenção à LGPD: restrinja exibição/uso de dados pessoais ao necessário.

## sales
- Chaves: id (PK), store_id (FK → stores.id), customer_id (FK opcional → customers.id), channel_id (FK → channels.id)
- Colunas: id, store_id, customer_id, channel_id, customer_name (text),
          created_at (timestamp), sale_status_desc (text: 'COMPLETED'|'CANCELLED'),
          total_amount_items (numeric), total_discount (numeric), total_increase (numeric),
          delivery_fee (numeric), service_tax_fee (numeric),
          total_amount (numeric), value_paid (numeric),
          production_seconds (int), delivery_seconds (int),
          discount_reason (text), people_quantity (int), origin (text)
- Propósito: Fato de pedidos (grão = 1 por venda).
- Notas:
  - Default analítico: filtrar `COMPLETED` + janela temporal.
  - `delivery_seconds` só faz sentido para canais de delivery.
  - `customer_name` pode divergir de `customers.customer_name` (entrada manual no pedido).

## product_sales
- Chaves: id (PK), sale_id (FK → sales.id), product_id (FK → products.id)
- Colunas: id, sale_id, product_id, quantity (numeric/int),
          base_price (numeric), total_price (numeric)
- Propósito: Itens de produto por venda (grão produto-venda).
- Notas:
  - Base para Top-N de produtos (unidades/receita).
  - Evite multiplicação de linhas ao juntar com `item_product_sales` sem agregar.

## item_product_sales
- Chaves: product_sale_id (FK → product_sales.id), item_id (FK → items.id), option_group_id (FK opcional → option_groups.id)
- Colunas: product_sale_id, item_id, option_group_id,
          quantity (numeric/int), additional_price (numeric),
          price (numeric), amount (numeric)
- Propósito: Complementos/opções aplicados a um produto vendido.
- Notas:
  - Em geral, `amount ≈ quantity * price` (confirme regra do seu PDV).
  - `additional_price` pode representar acréscimo atrelado ao item complementado.
  - Agregue por `product_sale_id` antes de combinar com métricas de `product_sales`.

## delivery_sales
- Chaves: id (PK), sale_id (FK → sales.id)
- Colunas: id, sale_id, courier_name (text), courier_phone (text),
          courier_type (text), delivery_type (text),
          status (text), delivery_fee (numeric), courier_fee (numeric)
- Propósito: Metadados da entrega (plataforma/operador/taxas).
- Notas:
  - Existe apenas para canais de delivery.
  - `delivery_fee` também consta em `sales` — defina fonte preferida por padrão analítico.

## delivery_addresses
- Chaves: delivery_sale_id (FK → delivery_sales.id), sale_id (FK → sales.id)
- Colunas: sale_id, delivery_sale_id, street (text), number (text),
          complement (text), neighborhood (text), city (text),
          state (text), postal_code (text),
          latitude (numeric), longitude (numeric)
- Propósito: Endereço e geolocalização do destino de entrega.
- Notas:
  - Relacionamento 1:1 com `delivery_sales`.
  - Caminho de join recomendado: `sales` → `delivery_sales` (LEFT) → `delivery_addresses` (LEFT).

## payments
- Chaves: (sale_id FK → sales.id), payment_type_id (FK → payment_types.id)
- Colunas: sale_id, payment_type_id, value (numeric)
- Propósito: Composição de pagamento por venda (pode haver múltiplas linhas por pedido).
- Notas:
  - Use `SUM(value)` por `sale_id` para comparar com `sales.value_paid`/`sales.total_amount`.
  - `LEFT JOIN` quando quiser preservar todas as vendas mesmo sem pagamento registrado.

---

## Observações Transversais
- Tipos esperados:
  - IDs inteiros; valores monetários em numeric/decimal; timestamps em UTC (verificar timezone de origem).
- Filtros padrão para análises:
  - Período relativo + `sale_status_desc='COMPLETED'`.
- Boas práticas de join:
  - Reduza o conjunto em `sales` antes de juntar com `product_sales`/`item_product_sales`.
  - Use `LEFT JOIN` para dimensões opcionais (`customers`, `payments`, `delivery_*`).
- Métricas e fontes:
  - Receita por venda: `sales.total_amount`.
  - Receita por produto: `product_sales.total_price`.
  - Itens/complementos: `item_product_sales.amount` ou `quantity * price` (conforme regra).
- Sanity checks sugeridos:
  - `SUM(payments.value)` por `sale_id` ≈ `sales.value_paid` (diferenças possíveis por troco/descontos).
  - `products.category_id` → `categories.type='P'`; `items.category_id` → `type='I'`.
  - Nem todo `channels.type='D'` terá `delivery_sales/addresses` em dados incompletos (prefira LEFT JOIN).