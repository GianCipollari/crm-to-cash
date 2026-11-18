-- Every dollar collected must be attributed to a won deal in the reconciliation fact.
-- Returns a row if money collected on invoices is missing from (or doubled in) the fact.

with invoices as (

    select coalesce(sum(net_collected), 0) as total
    from {{ ref('int_invoice_payments') }}

),

fact as (

    select coalesce(sum(net_collected), 0) as total
    from {{ ref('fct_deal_reconciliation') }}
    where invoice_id is not null

)

select invoices.total as collected_on_invoices, fact.total as collected_in_fact
from invoices, fact
where abs(invoices.total - fact.total) > 0.005
