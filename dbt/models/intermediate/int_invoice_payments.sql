-- One row per invoice with what was collected, refunded and still owed.
-- Payments reach an invoice in two ways (see stg_stripe__payment_intents):
--   invoice_payment: linked by invoice_id
--   standalone     : partial payment linked by invoice_external_id in metadata

with invoices as (

    select * from {{ ref('stg_stripe__invoices') }}

),

payments as (

    select * from {{ ref('stg_stripe__payment_intents') }}
    where status = 'succeeded'

),

refunds_per_payment as (

    select payment_intent_id, sum(amount) as amount_refunded, max(refunded_date) as refunded_date
    from {{ ref('stg_stripe__refunds') }}
    where status = 'succeeded'
    group by 1

),

payments_per_invoice as (

    select
        i.invoice_id,
        count(p.payment_intent_id)                  as payment_count,
        coalesce(sum(p.amount_received), 0)          as amount_collected,
        coalesce(sum(r.amount_refunded), 0)          as amount_refunded,
        max(p.paid_date)                             as last_paid_date,
        max(r.refunded_date)                         as refunded_date
    from invoices as i
    left join payments as p
        on (p.payment_kind = 'invoice_payment' and p.invoice_id = i.invoice_id)
        or (p.payment_kind = 'standalone' and p.invoice_external_id = i.invoice_external_id)
    left join refunds_per_payment as r on p.payment_intent_id = r.payment_intent_id
    group by 1

)

select
    i.invoice_id,
    i.invoice_external_id,
    i.crm_deal_id,
    i.customer_id,
    i.status,
    i.amount_due,
    i.invoice_date,
    i.due_date,
    pp.payment_count,
    pp.amount_collected,
    pp.amount_refunded,
    pp.amount_collected - pp.amount_refunded         as net_collected,
    i.amount_due - pp.amount_collected               as balance_due,
    pp.last_paid_date,
    pp.refunded_date,
    case
        when pp.amount_collected = 0 then 'unpaid'
        when pp.amount_collected < i.amount_due then 'partial'
        else 'paid'
    end                                              as payment_status,
    pp.amount_refunded > 0                           as is_refunded,
    i.amount_due - pp.amount_collected > 0
        and i.due_date < {{ as_of_date() }}          as is_overdue
from invoices as i
inner join payments_per_invoice as pp on i.invoice_id = pp.invoice_id
