{#
  Small helpers shared by the staging models.
  Raw tables store each API record as JSON text in `payload`; these macros
  pull fields out of it and convert them to proper types.
  All timestamps are returned as UTC without a time zone, so the result never
  depends on the time zone of the computer running dbt.

  Each macro uses adapter.dispatch: dbt picks snowflake__<name> when the target
  is Snowflake and default__<name> (DuckDB) otherwise. Models stay identical.
#}

{# A field from the JSON payload, as text. Example: json_text('$.properties.name') #}
{% macro json_text(path) -%}
    {{ return(adapter.dispatch('json_text')(path)) }}
{%- endmacro %}

{% macro default__json_text(path) -%}
    json_extract_string(payload, '{{ path }}')
{%- endmacro %}

{% macro snowflake__json_text(path) -%}
    get_path(parse_json(payload), '{{ path | replace("$.", "", 1) }}')::varchar
{%- endmacro %}


{# ISO 8601 text ("2026-11-06T20:05:12.345Z" or "...+00:00") -> timestamp in UTC #}
{% macro iso_to_timestamp(expr) -%}
    {{ return(adapter.dispatch('iso_to_timestamp')(expr)) }}
{%- endmacro %}

{% macro default__iso_to_timestamp(expr) -%}
    try_cast(replace(regexp_replace({{ expr }}, '(Z|\+00:00)$', ''), 'T', ' ') as timestamp)
{%- endmacro %}

{% macro snowflake__iso_to_timestamp(expr) -%}
    convert_timezone('UTC', try_to_timestamp_tz({{ expr }}))::timestamp_ntz
{%- endmacro %}


{#
  HubSpot date -> date. Date properties can come back as "2026-03-05",
  as an ISO timestamp at midnight UTC, or as epoch milliseconds.
  Taking the first 10 characters keeps the UTC day: this is what fixes the
  "closes at 21:00 the day before" effect seen in the HubSpot interface.
#}
{% macro hubspot_date(expr) -%}
    {{ return(adapter.dispatch('hubspot_date')(expr)) }}
{%- endmacro %}

{% macro default__hubspot_date(expr) -%}
    case
        when regexp_matches({{ expr }}, '^[0-9]+$') then cast(epoch_ms(cast({{ expr }} as bigint)) as date)
        else try_cast(left({{ expr }}, 10) as date)
    end
{%- endmacro %}

{% macro snowflake__hubspot_date(expr) -%}
    case
        when regexp_like({{ expr }}, '^[0-9]+$') then to_date(to_timestamp_ntz({{ expr }}::number, 3))
        else try_to_date(left({{ expr }}, 10))
    end
{%- endmacro %}


{# Stripe unix seconds -> timestamp in UTC #}
{% macro epoch_to_timestamp(expr) -%}
    {{ return(adapter.dispatch('epoch_to_timestamp')(expr)) }}
{%- endmacro %}

{% macro default__epoch_to_timestamp(expr) -%}
    epoch_ms(cast({{ expr }} as bigint) * 1000)
{%- endmacro %}

{% macro snowflake__epoch_to_timestamp(expr) -%}
    to_timestamp_ntz({{ expr }}::number)
{%- endmacro %}


{# Stripe amounts come in cents -> currency units with 2 decimals (same SQL everywhere) #}
{% macro cents_to_amount(expr) -%}
    cast(cast({{ expr }} as bigint) / 100.0 as decimal(14, 2))
{%- endmacro %}
