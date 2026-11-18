-- One row per day, from the start of the seed period to 60 days ahead.
-- Lets dashboards group by month or quarter and show days with no activity.
-- date_spine() writes the day generator each warehouse understands.

with days as (

    {{ date_spine('2025-11-01', as_of_date() ~ " + interval '60 day'") }}

)

select
    date_day,
    extract(year from date_day)            as year,
    extract(quarter from date_day)         as quarter,
    extract(month from date_day)           as month,
    {{ year_month('date_day') }}           as year_month,
    {{ iso_day_of_week('date_day') }}      as day_of_week,   -- 1 = Monday
    {{ iso_day_of_week('date_day') }} >= 6 as is_weekend,
    date_day <= {{ as_of_date() }}         as is_past
from days
