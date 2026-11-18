-- Source queries run on the DuckDB warehouse at build time (npm run sources);
-- each one becomes a table the pages query as warehouse.<file name>.
select
    deal_id,
    external_id,
    replace(sales_rep, '_', ' ')  as sales_rep,
    product,
    close_date,
    close_month,
    deal_amount,
    invoice_amount,
    net_collected,
    gap_amount,
    reconciliation_status,
    is_duplicate
from fct_deal_reconciliation
