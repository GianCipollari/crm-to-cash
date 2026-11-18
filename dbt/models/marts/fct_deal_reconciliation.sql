-- One row per won deal: what sales reported, what was billed, what was collected,
-- and a single reconciliation status that explains any gap.
-- Answers business questions 1 (share of won revenue collected) and 2 (where the gap is).

with deals as (

    select * from {{ ref('int_deals_with_invoices') }}

),

duplicates as (

    select deal_id, duplicate_of_external_id
    from {{ ref('int_deal_duplicates') }}

),

joined as (

    select
        d.*,
        dup.duplicate_of_external_id,
        dup.deal_id is not null as is_duplicate
    from deals as d
    left join duplicates as dup on d.deal_id = dup.deal_id

),

final as (

    select
        deal_id,
        external_id,
        company_id,
        contact_id,
        sales_rep,
        product,
        close_date,
        {{ year_month('close_date') }}                       as close_month,

        -- the three amounts that should agree
        deal_amount,
        invoice_amount,
        coalesce(net_collected, 0)                           as net_collected,

        -- details of the billing side
        invoice_id,
        invoice_external_id,
        invoice_match_method,
        invoice_date,
        due_date,
        coalesce(amount_collected, 0)                        as amount_collected,
        coalesce(amount_refunded, 0)                         as amount_refunded,
        balance_due,
        amount_difference,
        last_paid_date,
        last_paid_date - close_date                          as days_close_to_payment,
        is_duplicate,
        duplicate_of_external_id,

        -- revenue still not in the bank (duplicates are not real revenue)
        case when is_duplicate then 0
             else deal_amount - coalesce(net_collected, 0)
        end                                                  as gap_amount,

        -- first matching rule wins: order goes from structural to payment problems
        case
            when is_duplicate                                         then 'duplicate'
            when invoice_id is null
                 and close_date >= {{ as_of_date() }} - interval '10 day' then 'pending_invoice'
            when invoice_id is null                                   then 'missing_invoice'
            when is_refunded                                          then 'refunded'
            when payment_status = 'partial'                           then 'partial_payment'
            when payment_status = 'unpaid' and is_overdue             then 'unpaid_overdue'
            when payment_status = 'unpaid'                            then 'not_yet_due'
            when abs(amount_difference) > {{ var('amount_tolerance') }} * deal_amount
                                                                      then 'amount_mismatch'
            when last_paid_date < close_date                          then 'late_stage_update'
            else 'reconciled'
        end                                                  as reconciliation_status

    from joined

)

select * from final
