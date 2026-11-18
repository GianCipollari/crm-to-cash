-- One row per sales rep, as stored in the CRM's sales_rep property.

select
    sales_rep,
    replace(sales_rep, '_', ' ')    as sales_rep_name,
    count(*)                        as deals_count,
    min(deal_created_date)          as first_deal_date
from {{ ref('stg_hubspot__deals') }}
where sales_rep is not null
group by 1, 2
