┌─────────────────────────────────────────────┐
                                   │           CALLING SERVICES (1..N)            │
                                   │  Billing | Marketing | OTP/Auth | Shipping   │
                                   │  (each tags: channel + priority P0/P1/P2)    │
                                   └───────────────────────┬─────────────────────┘
                                                           │  HTTPS (mTLS, internal-only)
                                                           │  Idempotency-Key header
                                                           ▼
        ┌──────────────────────────────────────────────────────────────────────────────────────┐
        │                         NOTIFICATION SERVERS (stateless, autoscaled)                   │
        │                                                                                        │
        │   [AuthN/AuthZ: appKey/appSecret + mTLS]                                                │
        │            │                                                                           │
        │            ▼                                                                           │
        │   [Validation: email/phone/token format, payload schema, status codes]                 │
        │            │                                                                           │
        │            ▼                                                                           │
        │   [RATE LIMITING]                                                                       │
        │     • API throttle  → Token Bucket  (Redis, per-service)                                │
        │     • User freq cap → Sliding Window (Redis, key=user:category, TTL)                    │
        │            │                                                                           │
        │            ▼                                                                           │
        │   [IDEMPOTENCY / DEDUP]  Redis SET NX event_id, TTL=dedup window                        │
        │            │                                                                           │
        │            ▼                                                                           │
        │   [Settings check: opt-in? quiet hours? channel pref?]  ◄── Cache (read-through)        │
        │            │                                                                           │
        │            ▼                                                                           │
        │   [Enrich: user info, device tokens, template render]   ◄── Cache ◄── Read Replicas     │
        │            │                                                                           │
        │            ▼                                                                           │
        │   [Persist log row: status=QUEUED]  ──────────────────────► Notification Log (write)   │
        │            │                                                                           │
        │   [SCHEDULER PATH]  if send_at in future → Schedule store / delay queue (not shown      │
        │                     in detail) → re-injects here at fire time (TZ-aware)                │
        │            │                                                                           │
        │            ▼  route by (channel, priority)                                              │
        └────────────┼───────────────────────────────────────────────────────────────────────────┘
                     │
                     ▼
   ┌───────────────────────────────────────────────────────────────────────────────────────────┐
   │                          MESSAGE QUEUES  (per channel × per priority)                       │
   │                                                                                             │
   │   PUSH:  push.p0   push.p1   push.p2          SMS:  sms.p0   sms.p1   sms.p2                 │
   │   EMAIL: email.p0  email.p1  email.p2                                                        │
   │                                                                                             │
   │   Drain order: P0 → P1 → P2 with weighted fairness (e.g. 70/20/10) to avoid starvation      │
   └───────────────┬───────────────────────────┬────────────────────────────┬───────────────────┘
                   │                           │                            │
                   ▼                           ▼                            ▼
        ┌─────────────────┐         ┌─────────────────┐          ┌─────────────────┐
        │  PUSH WORKERS   │         │  SMS WORKERS    │          │  EMAIL WORKERS  │
        │  (autoscale on  │         │  (autoscale on  │          │  (autoscale on  │
        │   queue depth)  │         │   queue depth)  │          │   queue depth)  │
        └────────┬────────┘         └────────┬────────┘          └────────┬────────┘
                 │                           │                            │
                 ▼                           ▼                            ▼
        ┌─────────────────────────────────────────────────────────────────────────────┐
        │            PROVIDER ABSTRACTION LAYER  (adapter pattern + router)             │
        │                                                                               │
        │   Router picks by: circuit-breaker state · health check · region · cost       │
        │   Carries Idempotency-Key through failover (no double-send)                    │
        │                                                                               │
        │   PUSH:  [CB] APNS ──► fallback (region)                                       │
        │          [CB] FCM  ──► fallback Jpush/PushY (e.g. China)                        │
        │   SMS:   [CB] Twilio ──► [CB] Nexmo   (failover + least-cost routing)          │
        │   EMAIL: [CB] SendGrid ──► [CB] Mailgun                                         │
        │                                                                               │
        │   On transient err → RETRY (exp backoff + jitter, max N) → else DLQ            │
        │   On permanent err (invalid token / unsubscribed / 4xx) → SUPPRESS, no retry   │
        └───────────────┬───────────────────────────────────────────────┬───────────────┘
                        │ success/failure                                │ permanent failures
                        ▼                                                ▼
            ┌──────────────────────┐                          ┌──────────────────────┐
            │  Update Log status   │                          │   DEAD LETTER QUEUE  │
            │  SENT / FAILED       │                          │   (alert + manual     │
            └──────────────────────┘                          │    replay)            │
                                                              └──────────────────────┘
                        ▲
                        │ async delivery receipts (delivered/bounced/unregistered/complaint)
                        │
        ┌───────────────┴───────────────────────────────────────────────────────────────┐
        │                    DELIVERY-RECEIPT / WEBHOOK INGESTION                         │
        │   Endpoints for APNS/FCM/Twilio/SendGrid callbacks →                            │
        │     • update log status                                                         │
        │     • remove dead device tokens (FCM/APNS "unregistered")                       │
        │     • suppress on email bounce/complaint, SMS opt-out                           │
        └───────────────┬────────────────────────────────────────────────────────────────┘
                        │
                        ▼
        ┌───────────────────────────────┐        ┌──────────────────────────────────────┐
        │        ANALYTICS / EVENTS     │        │           MONITORING / ALERTS         │
        │  open rate · click · delivery │        │  queue depth → autoscale workers      │
        │  → event stream → warehouse   │        │  provider error rate · breaker trips  │
        └───────────────────────────────┘        │  retry/DLQ rate · latency p50/p99     │
                                                 └──────────────────────────────────────┘

   ┌─────────────────────────────────────── DATA TIER ───────────────────────────────────────────┐
   │                                                                                              │
   │  CACHE (Redis):  user info · device tokens · settings · rendered templates ·                 │
   │                  rate-limit buckets/windows · dedup keys                                      │
   │                                                                                              │
   │  PRIMARY DB (PostgreSQL):  user | device | notification_settings | template                  │
   │     └─ Read Replicas (hot-path metadata reads)                                                │
   │                                                                                              │
   │  NOTIFICATION LOG:  time-partitioned (daily) · status tracking ·                             │
   │     └─ 30–90d hot → archive to OBJECT STORE (S3, Parquet) for analytics                       │
   │                                                                                              │
   │  OBJECT STORE (S3):  large payloads (referenced by log row) · archived logs                  │
   └──────────────────────────────────────────────────────────────────────────────────────────────┘

   Cross-cutting: multi-region/AZ for no SPOF · TLS in transit · PII encrypted at rest ·
   GDPR/CAN-SPAM (unsubscribe) · audit logging