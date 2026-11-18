{#
  "Today" for the business logic (overdue invoices). Pass a fixed date to make a
  run reproducible:  dbt build --vars "as_of_date: 2026-11-13"
#}
{% macro as_of_date() -%}
    {%- if var('as_of_date', none) -%}
        cast('{{ var("as_of_date") }}' as date)
    {%- else -%}
        current_date
    {%- endif -%}
{%- endmacro %}


{# Replace every match of a regular expression (DuckDB needs the 'g' flag; Snowflake replaces all by default) #}
{% macro regexp_replace_all(expr, pattern, replacement) -%}
    {{ return(adapter.dispatch('regexp_replace_all')(expr, pattern, replacement)) }}
{%- endmacro %}

{% macro default__regexp_replace_all(expr, pattern, replacement) -%}
    regexp_replace({{ expr }}, '{{ pattern }}', '{{ replacement }}', 'g')
{%- endmacro %}

{% macro snowflake__regexp_replace_all(expr, pattern, replacement) -%}
    regexp_replace({{ expr }}, '{{ pattern }}', '{{ replacement }}')
{%- endmacro %}


{#
  Company name in a comparable form: no accents, lower case, no punctuation and
  no legal form, so "Atlántico Farma Ltda." and "ATLANTICO FARMA LTDA" are equal.
  translate() exists in both warehouses, unlike strip_accents().
#}
{% macro normalize_company_name(expr) -%}
    trim({{ regexp_replace_all(
        regexp_replace_all(
            "translate(lower(" ~ expr ~ "), 'áàäâéèëêíìïîóòöôúùüûñç', 'aaaaeeeeiiiioooouuuunc')",
            '[^a-z0-9 ]', ''),
        '[ ]+(sa de cv|sa|srl|sas|ltda)$', '') }})
{%- endmacro %}


{# Month label "2026-11" from a date #}
{% macro year_month(expr) -%}
    {{ return(adapter.dispatch('year_month')(expr)) }}
{%- endmacro %}

{% macro default__year_month(expr) -%}
    strftime({{ expr }}, '%Y-%m')
{%- endmacro %}

{% macro snowflake__year_month(expr) -%}
    to_char({{ expr }}, 'YYYY-MM')
{%- endmacro %}


{# ISO day of week: 1 = Monday ... 7 = Sunday #}
{% macro iso_day_of_week(expr) -%}
    {{ return(adapter.dispatch('iso_day_of_week')(expr)) }}
{%- endmacro %}

{% macro default__iso_day_of_week(expr) -%}
    extract(isodow from {{ expr }})
{%- endmacro %}

{% macro snowflake__iso_day_of_week(expr) -%}
    dayofweekiso({{ expr }})
{%- endmacro %}


{# One row per day, column date_day, from start_date to end_expr (both inclusive) #}
{% macro date_spine(start_date, end_expr) -%}
    {{ return(adapter.dispatch('date_spine')(start_date, end_expr)) }}
{%- endmacro %}

{% macro default__date_spine(start_date, end_expr) -%}
    select cast(generate_series as date) as date_day
    from generate_series(cast('{{ start_date }}' as timestamp), cast({{ end_expr }} as timestamp), interval '1 day')
{%- endmacro %}

{% macro snowflake__date_spine(start_date, end_expr) -%}
    select date_day
    from (
        select dateadd(day, row_number() over (order by seq4()) - 1, '{{ start_date }}'::date) as date_day
        from table(generator(rowcount => 3000))
    ) as days
    where date_day <= {{ end_expr }}
{%- endmacro %}
