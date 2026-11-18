-- Won deals that look like the same sale logged twice: same company, same amount,
-- close dates at most 3 days apart. The deal with the later external id is flagged
-- as the duplicate of the earlier one, unless billing confirms it is a real sale:
-- an invoice that references the deal by its CRM id means it is not a duplicate.

with won_deals as (

    select * from {{ ref('stg_hubspot__deals') }}
    where is_won

),

billed_by_reference as (

    select deal_id
    from {{ ref('int_deals_with_invoices') }}
    where invoice_match_method = 'deal_ref'

),

pairs as (

    select
        later.deal_id,
        later.external_id,
        later.sales_rep,
        earlier.deal_id         as duplicate_of_deal_id,
        earlier.external_id     as duplicate_of_external_id,
        earlier.sales_rep       as duplicate_of_sales_rep,
        later.amount,
        abs(later.close_date - earlier.close_date) as days_apart,
        row_number() over (partition by later.deal_id order by earlier.external_id) as rn
    from won_deals as later
    inner join won_deals as earlier
        on later.company_id = earlier.company_id
        and later.amount = earlier.amount
        and later.external_id > earlier.external_id
        and abs(later.close_date - earlier.close_date) <= 3
    where later.deal_id not in (select deal_id from billed_by_reference)

)

select * exclude (rn)
from pairs
where rn = 1
