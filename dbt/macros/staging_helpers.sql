{#
  Small helpers shared by the staging models.
  Raw tables store each API record as JSON text in `payload`; these macros
  pull fields out of it and convert them to proper types.
  All timestamps are returned as UTC without a time zone, so the result never
  depends on the time zone of the computer running dbt.
#}

{# A field from the JSON payload, as text. Example: json_text('$.properties.name') #}
{% macro json_text(path) -%}
    json_extract_string(payload, '{{ path }}')
{%- endmacro %}


{# ISO 8601 text ("2026-11-06T20:05:12.345Z" or "...+00:00") -> timestamp in UTC #}
{% macro iso_to_timestamp(expr) -%}
    try_cast(replace(regexp_replace({{ expr }}, '(Z|\+00:00)$', ''), 'T', ' ') as timestamp)
{%- endmacro %}


{#
  HubSpot date -> date. Date properties can come back as "2026-03-05",
  as an ISO timestamp at midnight UTC, or as epoch milliseconds.
  Taking the first 10 characters keeps the UTC day: this is what fixes the
  "closes at 21:00 the day before" effect seen in the HubSpot interface.
#}
{% macro hubspot_date(expr) -%}
    case
        when regexp_matches({{ expr }}, '^[0-9]+$') then cast(epoch_ms(cast({{ expr }} as bigint)) as date)
        else try_cast(left({{ expr }}, 10) as date)
    end
{%- endmacro %}


{# Stripe unix seconds -> timestamp in UTC #}
{% macro epoch_to_timestamp(expr) -%}
    epoch_ms(cast({{ expr }} as bigint) * 1000)
{%- endmacro %}


{# Stripe amounts come in cents -> currency units with 2 decimals #}
{% macro cents_to_amount(expr) -%}
    cast(cast({{ expr }} as bigint) / 100.0 as decimal(14, 2))
{%- endmacro %}
