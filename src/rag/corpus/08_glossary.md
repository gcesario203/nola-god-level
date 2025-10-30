
# Glossário de Sinônimos (RAG / Query Builder)

Este glossário mapeia termos comuns usados pelos usuários em linguagem natural para os nomes de tabelas, colunas e métricas do esquema de restaurantes. O objetivo é permitir consultas mais intuitivas no Query Builder e reduzir ambiguidades.

---

## Entidades Principais

| Termos do Usuário | Entidade / Tabela | Observações |
|-------------------|-------------------|-------------|
| venda, pedido, transação | sales | Fato principal – contém status, valores e timestamps |
| produto, item de cardápio, prato | products | Produtos vendidos (nível principal) |
| item, complemento, adicional | items | Complementos vinculados a produtos (via item_product_sales) |
| cliente, consumidor, comprador | customers | Dados de cliente (nome, e-mail, etc.) |
| loja, unidade, ponto de venda | stores | Identificação física da loja |
| canal, origem da venda, marketplace | channels | Ex.: Delivery, Presencial |
| pagamento, recibo, quitação | payments | Tipos e valores de pagamento |
| tipo de pagamento, método de pagamento | payment_types | Cartão, Dinheiro, Pix etc. |
| marca, brand, bandeira | brands | Agrupamento de sub-marcas |
| sub-marca, unidade de marca | sub_brands | Sub-nível da marca |
| categoria, grupo de produto | categories | type='P' para produtos, type='I' para itens |

---

## Métricas e Medidas

| Termos do Usuário | Campo / Cálculo | Descrição |
|-------------------|------------------|-----------|
| faturamento, receita, total vendido | SUM(s.total_amount) | Soma total das vendas concluídas |
| número de vendas, quantidade de pedidos | COUNT(DISTINCT s.id) | Contagem de pedidos únicos |
| ticket médio, valor médio por venda | SUM(s.total_amount) / NULLIF(COUNT(DISTINCT s.id), 0) | Receita média por pedido |
| descontos, promoções aplicadas | SUM(s.total_discount) | Descontos presentes no pedido |
| taxa de serviço | SUM(s.service_tax_fee) | Taxa cobrada em alguns canais |
| taxa de entrega, frete | SUM(s.delivery_fee) | Valor somado do campo delivery_fee |
| tempo de entrega, SLA de entrega | AVG(s.delivery_seconds) / percentis | Tempo médio/percentil entre pedido e entrega |
| pagamentos, valor pago | SUM(p.value) | Soma dos valores em payments |
| valor total pago | sales.value_paid | Valor líquido efetivamente pago pelo cliente |
| cancelamentos, pedidos cancelados | sale_status_desc = 'CANCELLED' | Vendas não concluídas |
| entregas, pedidos entregues | channels.type = 'D' + sale_status_desc = 'COMPLETED' | Foco em pedidos delivery |

---

## Dimensões / Filtros

| Termos do Usuário | Campo / Tradução | Observações |
|-------------------|-------------------|-------------|
| data, dia, período, semana, mês | sales.created_at | Usar DATE_TRUNC conforme granularidade |
| cidade, município | stores.city | Localização da loja |
| estado, UF | stores.state | Unidade federativa |
| marca | brands.name | Nome da marca principal |
| sub-marca | sub_brands.name | Agrupamento dentro da marca |
| canal, tipo de canal | channels.name / channels.type | “Delivery” ou “Presencial” |
| loja | stores.name | Identificação direta |
| cliente | customers.name / customers.id | Pode ser omitido em consultas agregadas |
| método de pagamento | payment_types.description | Ex.: Cartão, Pix, Dinheiro |
| origem do pedido | sales.origin | Ex.: POS, APP, WEB |

---

## Exemplos de Mapeamentos no Query Builder

| Pergunta do Usuário | Interpretação pelo RAG | SQL Base |
|---------------------|------------------------|---------|
| Qual o faturamento por loja nos últimos 30 dias? | receita = total_amount, entidade = sales, dimensão = store_id, filtro = 30d | Ver consulta padrão de faturamento por loja |
| Top 10 produtos mais vendidos por receita | produtos → products, receita → product_sales.total_price | Usa product_sales agregado |
| Tempo médio de entrega por canal | tempo de entrega = delivery_seconds, canal = channels | Filtra channels.type='D' |
| Número de clientes novos e recorrentes | entidade = customers, contagem por repetição de sales.customer_id | Usa CTE “recorrência” |

---

## Estrutura JSON sugerida (para o RAG/Query Builder)

```json
{
  "faturamento": ["total_amount", "receita", "valor total"],
  "ticket médio": ["ticket médio", "valor médio", "média de venda"],
  "canal": ["canal", "origem", "sales.channel_id", "channels.name"],
  "venda": ["venda", "pedido", "transação", "sales"],
  "cliente": ["cliente", "consumidor", "buyer", "sales.customer_id"],
  "loja": ["loja", "unidade", "ponto de venda", "stores"],
  "pagamento": ["pagamento", "payment", "recibo", "payments.value"]
}
```

Notas:
- As listas podem incluir tanto sinônimos em linguagem natural quanto referências diretas a colunas/tabelas para facilitar o mapeamento.
- Expanda com termos específicos do negócio (ex.: nomes de canais, categorias) conforme necessidade.

