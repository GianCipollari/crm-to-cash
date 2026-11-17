{#
  History of every deal: a new row each time its stage, amount or close date
  changes (raw only keeps the latest version). dbt adds dbt_valid_from and
  dbt_valid_to to each row.
#}
{% snapshot snap_deals %}

{{ config(
    unique_key='deal_id',
    strategy='check',
    check_cols=['deal_stage', 'amount', 'close_date'],
) }}

select
    deal_id,
    external_id,
    deal_stage,
    amount,
    close_date,
    sales_rep
from {{ ref('stg_hubspot__deals') }}

{% endsnapshot %}
