-- Mercedes CLE Emissions — Appeal & Quantum Trial Update (November 2026, ADT-3640), master campaign 937, list 105.
-- List 104 (ADT-3640 test send) is excluded.
-- Deduplicated to ONE row per email: the latest event by date_updated wins.
-- claim_id here is the 00ID (Sendy custom field); resolve the real claim_id
-- afterwards via Email_list_mer.csv (User_id -> claim_id, 1:1).
SELECT
    id,
    recipient,
    notification_timestamp,
    messageId,
    claim_id,
    user_id,
    list_id,
    master_campaign_id,
    reminder_subject,
    opened,
    clicked,
    bounced,
    complaint
FROM (
    SELECT
        s.id,
        s.email AS recipient,
        e.date_updated AS notification_timestamp,
        s.messageID AS messageId,
        s.custom_fields AS claim_id,
        s.custom_fields AS user_id,  -- 00ID (Sendy custom field)
        s.list AS list_id,
        c.master_campaign_id,
        c.title AS reminder_subject,
        e.Opened AS opened,
        e.Clicked AS clicked,
        COALESCE(e.HardBounce, e.SoftBounce, e.OtherBounce, s.bounced) AS bounced,
        COALESCE(e.Complaint, s.complaint) AS complaint,
        ROW_NUMBER() OVER (
            PARTITION BY s.email
            ORDER BY e.date_updated DESC
        ) AS rn
    FROM sendy.subscribers s
    JOIN sendy.campaign_events_results e
        ON s.id = e.subscriber_id
    JOIN sendy.campaigns c
        ON e.campaign_id = c.id
    WHERE c.master_campaign_id = 937
      AND s.list = 105
      AND e.date_updated > %s
) t
WHERE rn = 1;
