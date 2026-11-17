-- One row per day, from the start of the seed period to 60 days ahead.
-- Lets dashboards group by month or quarter and show days with no activity.

with days as (

    select cast(generate_series as date) as date_day
    from generate_series(
        timestamp '2025-11-01',
        cast({{ as_of_date() }} as timestamp) + interval 60 day,
        interval 1 day
    )

)

select
    date_day,
    extract(year from date_day)         as year,
    extract(quarter from date_day)      as quarter,
    extract(month from date_day)        as month,
    strftime(date_day, '%Y-%m')         as year_month,
    extract(isodow from date_day)       as day_of_week,   -- 1 = Monday
    extract(isodow from date_day) >= 6  as is_weekend,
    date_day <= {{ as_of_date() }}      as is_past
from days
