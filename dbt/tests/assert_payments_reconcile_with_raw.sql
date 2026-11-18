-- The pipeline reconciles itself: total received in staging must equal the total
-- in the raw JSON. Any row returned means money was lost or duplicated in staging.

with staging as (

    select coalesce(sum(amount_received), 0) as total
    from {{ ref('stg_stripe__payment_intents') }}

),

raw as (

    select coalesce(sum(cast({{ json_text('$.amount_received') }} as bigint)), 0) / 100.0 as total
    from {{ source('raw', 'raw_stripe_payment_intents') }}

)

select staging.total as staging_total, raw.total as raw_total
from staging, raw
where abs(staging.total - raw.total) > 0.005
