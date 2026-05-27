# G2 Aggregate Report

## Authoritative mart
- Chosen: `lottemart`
- Reason: emart recon decision was sparse (1 fixture categories); lottemart has richest harvested tree (320 fixture categories).

## Counts per mart
| mart | DB distinct native paths | fixture categories | mapped source_native values |
| --- | ---: | ---: | ---: |
| emart | 1 | 1 | 1 |
| homeplus | 3 | 54 | 1 |
| lottemart | 5 | 320 | 324 |
| costco | 2 | 4 | 4 |

## Review queue stats
- total: 58
- emart: 2
- homeplus: 54
- lottemart: 0
- costco: 2

## Sample tree YAML excerpt
```yaml
schema: unified_category_tree.v1
authoritative_mart: lottemart
nodes:
- id: food
  name: 식품
  parent_id: null
  children:
  - food.fruit
  - food.vegetables
  - food.rice-grains
  - food.meat-eggs
  - food.seafood
  - food.deli
  - food.bakery
  - food.dairy
  - food.kimchi-sides
  - food.noodles-rice
  - food.condiments
  - food.ready-meals
  - food.snacks
  - food.icecream
  - food.beverages
  - food.coffee-tea
  - food.health-food
  - food.imported
  source_natives:
    emart:
    - '6000095494'
    homeplus:
    - '1'
    lottemart:
    - '001'
    - '001001'
    - '001002'
    - '001003'
    - '001004'
    - '...'
    costco:
    - '801234'
    - '999999'
    - cos_10
    - cos_10.1
- id: food.dairy
  name: 우유/유제품
  parent_id: food
  children:
  - food.dairy.milk
  - food.dairy.soy-milk
  - food.dairy.yogurt
  - food.dairy.cheese-butter
  source_natives:
    emart: []
    homeplus: []
    lottemart:
    - 008
    - 008001
    - 008002
    - 008003
    - 008005
    - '...'
    costco: []
- id: food.dairy.milk
  name: 우유
  parent_id: food.dairy
  children: []
  source_natives:
    emart: []
    homeplus: []
    lottemart:
    - 008001
    - 008002
    - 008003
    - 008005
    - 008006
    - '...'
    costco: []
```

## Reproduction one-liner
`py -3 -m db_admin.backend.scripts.g2_category_aggregator --output devlog/round-R/g2-unified-tree.yaml`

## Inputs inventoried
- DB categories: 11 distinct rows from `products`.
- Fixture categories: 379 harvested rows from crawler fixtures.
