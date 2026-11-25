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
    s.userID AS user_id,
    NULL AS claim_status,
    NULL AS reminder_type,
    c.title AS reminder_subject,
    c.html_text AS message_body,
    NULL AS url,
    e.Opened AS opened,
    e.Clicked AS clicked,
    COALESCE(e.HardBounce, e.SoftBounce, e.OtherBounce, s.bounced) AS bounced,
    COALESCE(e.Complaint, s.complaint) AS complaint
FROM sendy.subscribers s
LEFT JOIN (
    SELECT cer.*,
           ROW_NUMBER() OVER (
               PARTITION BY cer.subscriber_id
               ORDER BY cer.date_updated DESC
           ) AS rn
    FROM sendy.campaign_events_results cer
) e
    ON s.id = e.subscriber_id
   AND e.rn = 1
LEFT JOIN sendy.campaigns c
    ON e.campaign_id = c.id
WHERE s.list IN (57, 58, 59, 60)
  AND e.date_updated > %s;
