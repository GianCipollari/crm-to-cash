-- One row per won deal, with the invoice that bills it (if any) and its payments.
-- Pass 1 (deal_ref)            : invoice metadata holds the CRM deal id.
-- Pass 2 (company_amount_date) : invoices without that reference are matched to a won
--   deal of the same company (via int_customers_matched), invoiced 0-15 days after the
--   close date; the closest amount, then the closest date, wins. One invoice per deal.

with won_deals as (

    select * from {{ ref('stg_hubspot__deals') }}
    where is_won

),

invoices as (

    select
        ip.*,
        cm.company_id
    from {{ ref('int_invoice_payments') }} as ip
    left join {{ ref('int_customers_matched') }} as cm on ip.customer_id = cm.customer_id

),

by_reference as (

    select d.deal_id, i.invoice_id, 'deal_ref' as invoice_match_method
    from won_deals as d
    inner join invoices as i on i.crm_deal_id = d.external_id

),

candidates as (

    select
        d.deal_id,
        i.invoice_id,
        row_number() over (
            partition by i.invoice_id
            order by abs(i.amount_due - d.amount), abs(i.invoice_date - d.close_date), d.external_id
        ) as rank_for_invoice
    from invoices as i
    inner join won_deals as d
        on i.company_id = d.company_id
        and i.invoice_date between d.close_date and d.close_date + interval 15 day
    where i.crm_deal_id is null
      and d.deal_id not in (select deal_id from by_reference)

),

by_company as (

    select deal_id, invoice_id, 'company_amount_date' as invoice_match_method
    from (
        select
            *,
            row_number() over (partition by deal_id order by invoice_id) as rank_for_deal
        from candidates
        where rank_for_invoice = 1
    )
    where rank_for_deal = 1

),

matches as (

    select * from by_reference
    union all
    select * from by_company

)

select
    d.deal_id,
    d.external_id,
    d.company_id,
    d.contact_id,
    d.sales_rep,
    d.product,
    d.amount                                         as deal_amount,
    d.close_date,
    m.invoice_id,
    coalesce(m.invoice_match_method, 'none')         as invoice_match_method,
    i.invoice_external_id,
    i.amount_due                                     as invoice_amount,
    i.amount_due - d.amount                          as amount_difference,
    i.invoice_date,
    i.due_date,
    i.amount_collected,
    i.amount_refunded,
    i.net_collected,
    i.balance_due,
    i.last_paid_date,
    i.payment_status,
    i.is_refunded,
    i.is_overdue
from won_deals as d
left join matches as m on d.deal_id = m.deal_id
left join invoices as i on m.invoice_id = i.invoice_id
