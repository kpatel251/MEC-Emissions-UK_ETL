-- Mercedes CLE Emissions — master campaign 924, lists 61 (initial) + 63 (follow-up).
-- Deduplicated to ONE row per email: the follow-up (list 63) replaces the initial
-- send (list 61) when present, otherwise the latest event by date_updated wins.
-- Keeps the incremental `%s` watermark param so it runs in the Glue/local pipeline.
SELECT
    id,
    notification_type,
    notification_subtype,
    recipient,
    notification_timestamp,
    message_status,
    message_action,
    diagnosticCode,
    original_timestamp,
    messageId,
    claim_id,
    user_id,
    claim_status,
    reminder_type,
    reminder_subject,
    message_body,
    url,
    opened,
    clicked,
    bounced,
    complaint
FROM (
    SELECT
        s.id,
        NULL AS notification_type,
        NULL AS notification_subtype,
        s.email AS recipient,
        e.date_updated AS notification_timestamp,
        NULL AS message_status,
        NULL AS message_action,
        NULL AS diagnosticCode,
        NULL AS original_timestamp,
        s.messageID AS messageId,
        s.custom_fields AS claim_id,
        s.custom_fields AS user_id,  -- 00ID (Sendy custom field); replaces the constant s.userID
        NULL AS claim_status,
        NULL AS reminder_type,
        c.title AS reminder_subject,
        c.html_text AS message_body,
        NULL AS url,
        e.Opened AS opened,
        e.Clicked AS clicked,
        COALESCE(e.HardBounce, e.SoftBounce, e.OtherBounce, s.bounced) AS bounced,
        COALESCE(e.Complaint, s.complaint) AS complaint,
        ROW_NUMBER() OVER (
            PARTITION BY s.email
            ORDER BY (s.list = 63) DESC, e.date_updated DESC
        ) AS rn
    FROM sendy.subscribers s
    JOIN sendy.campaign_events_results e
        ON s.id = e.subscriber_id
    JOIN sendy.campaigns c
        ON e.campaign_id = c.id
    WHERE c.master_campaign_id = 924
      AND s.list IN (61, 63)
      AND e.date_updated > %s
) t
WHERE rn = 1;
