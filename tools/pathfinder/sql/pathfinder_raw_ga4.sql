-- Raw GA4 PathFinder extract.
--
-- The Python app replaces {{SOURCE_TABLE}} with a validated project.dataset.events_*
-- identifier and supplies the four query parameters below. The query deliberately:
--   * scans only stable daily tables, not events_intraday_*;
--   * returns hashed identifiers rather than raw user_id/user_pseudo_id;
--   * strips URL query strings;
--   * does not extract component_value, which has previously contained DOB/PII.

WITH raw AS (
  SELECT
    PARSE_DATE('%Y%m%d', event_date) AS event_date,
    TIMESTAMP_MICROS(event_timestamp) AS event_ts,
    event_timestamp,
    COALESCE(batch_page_id, 0) AS batch_page_id,
    COALESCE(batch_ordering_id, 0) AS batch_ordering_id,
    COALESCE(batch_event_index, 0) AS batch_event_index,
    event_name,
    platform,
    stream_id,
    COALESCE(device.category, 'unknown') AS device_category,
    COALESCE(traffic_source.source, '(direct)') AS first_user_source,
    COALESCE(traffic_source.medium, '(none)') AS first_user_medium,
    COALESCE(traffic_source.name, '(not set)') AS first_user_campaign,
    COALESCE(privacy_info.analytics_storage, 'Unset') AS analytics_storage,
    user_pseudo_id,
    CASE
      WHEN user_id IS NULL
        OR TRIM(user_id) = ''
        OR LOWER(TRIM(user_id)) = 'undefined'
      THEN NULL
      ELSE TRIM(user_id)
    END AS identified_id,
    (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id')
      AS ga_session_id,
    (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_number')
      AS ga_session_number,
    (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_location')
      AS page_location,
    (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_title')
      AS page_title,
    (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_path')
      AS page_path_param,
    (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'firebase_screen')
      AS firebase_screen,
    (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'firebase_screen_class')
      AS firebase_screen_class,
    (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'screen_name')
      AS screen_name_param,
    (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'form_id')
      AS form_id,
    (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'form_step_id')
      AS form_step_id,
    (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'component_id')
      AS component_id,
    (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'component_type')
      AS component_type,
    COALESCE(
      (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'component_validated'),
      CAST((SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'component_validated') AS STRING)
    ) AS component_validated,
    COALESCE(
      (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'sedol'),
      (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'instrument_code'),
      (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'epic'),
      (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'symbol')
    ) AS instrument_code
  FROM `{{SOURCE_TABLE}}`
  WHERE _TABLE_SUFFIX BETWEEN FORMAT_DATE('%Y%m%d', @start_date)
                          AND FORMAT_DATE('%Y%m%d', @end_date)
    AND event_name IN UNNEST(@event_names)
    AND user_pseudo_id IS NOT NULL
    AND COALESCE(privacy_info.analytics_storage, 'Unset')
        IN UNNEST(@analytics_storage_values)
),
shaped AS (
  SELECT
    * EXCEPT(
      user_pseudo_id,
      identified_id,
      page_location,
      page_path_param,
      firebase_screen,
      firebase_screen_class,
      screen_name_param
    ),
    TO_HEX(SHA256(user_pseudo_id)) AS browser_key,
    IF(identified_id IS NULL, NULL, TO_HEX(SHA256(identified_id)))
      AS identified_key,
    IF(
      ga_session_id IS NULL,
      NULL,
      TO_HEX(SHA256(CONCAT(user_pseudo_id, '|', CAST(ga_session_id AS STRING))))
    ) AS ga_session_key,
    CASE
      WHEN platform = 'WEB' THEN COALESCE(
        NULLIF(REGEXP_EXTRACT(page_location, r'^https?://[^/]+([^?#]*)'), ''),
        NULLIF(REGEXP_EXTRACT(page_location, r'^([^?#]*)'), ''),
        page_path_param
      )
      ELSE COALESCE(
        firebase_screen,
        screen_name_param,
        page_path_param,
        firebase_screen_class,
        page_title
      )
    END AS route_path
  FROM raw
)
SELECT *
FROM shaped
ORDER BY
  browser_key,
  event_timestamp,
  batch_page_id,
  batch_ordering_id,
  batch_event_index;
