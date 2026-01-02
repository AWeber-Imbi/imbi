# 3. Email Sending Architecture

Date: 2026-01-01

## Status

Accepted

## Context

Imbi v2 requires a transactional email system to support user workflows:
- Password reset for users who forget their credentials
- Welcome emails for new user onboarding
- Email verification for account security
- Security alerts for important account events (password changes, new logins)

### Requirements

1. **Email Types**:
   - Transactional emails only (no marketing or bulk campaigns)
   - Password reset with secure tokens
   - Welcome messages for new users
   - Email verification for account activation
   - Security notifications

2. **Template System**:
   - HTML and plain text versions for accessibility
   - Consistent branding across all emails
   - Template versioning through code review
   - Subject line templating

3. **Reliability**:
   - Automatic retry for transient failures
   - Track permanently failed emails for investigation
   - Non-blocking API requests (emails sent in background)
   - Audit trail for compliance

4. **Development Experience**:
   - Local testing without external dependencies
   - Easy to test email rendering
   - No production credentials needed for development

5. **Production Requirements**:
   - Support any SMTP server (no vendor lock-in)
   - Secure connection options (TLS/SSL)
   - Audit logging for compliance
   - Token management with expiry

## Decision

### 1. Email Delivery Method

**Direct SMTP (not third-party services)**

We will send emails directly via SMTP using Python's standard library `smtplib`.

**Rationale**:
- **No vendor lock-in**: Works with any SMTP server (AWS SES, SendGrid, Mailgun, corporate mail servers)
- **Cost control**: No per-email pricing, only SMTP server costs
- **Privacy**: Email content never sent to third-party APIs
- **Simplicity**: Standard library, no additional dependencies
- **Flexibility**: Easy to switch SMTP providers without code changes

**Trade-offs**:
- Must implement retry logic ourselves (third-party services handle this)
- No built-in analytics (open rates, click tracking)
- Acceptable: Retry logic is straightforward, analytics not needed for transactional emails

### 2. Template Storage Strategy

**Inline Templates in Source Code**

We will store Jinja2 templates in `src/imbi/email/templates/` packaged with the application code.

**Rationale**:
- **Version control**: Templates versioned alongside code
- **Code review**: Template changes go through PR review process
- **Deployment simplicity**: Templates bundled with application, no external files
- **Type safety**: Template paths are static, caught at import time
- **Testing**: Templates available in test environment automatically

**Trade-offs**:
- Cannot edit templates without redeployment
- Acceptable: Transactional emails should be stable, changes are infrequent

**Alternative Considered**:
- Database-stored templates: Allows runtime editing but adds complexity, no immediate need

### 3. Asynchronous Delivery

**FastAPI BackgroundTasks (not Celery)**

We will use FastAPI's `BackgroundTasks` to send emails after HTTP response returns.

**Rationale**:
- **Non-blocking**: API responses return immediately, email sending happens in background
- **Simple**: No additional infrastructure (no Redis, RabbitMQ, worker processes)
- **Sufficient**: Moderate email volume expected, BackgroundTasks handles this well
- **Built-in**: Native FastAPI feature, no external dependencies
- **Process-local**: Email sending happens in same process as request

**Trade-offs**:
- Emails lost if process crashes after response but before send completes
- Not suitable for high-volume scenarios (thousands of emails/minute)
- Acceptable: Low probability, retry logic handles transient failures, volume is moderate

**Alternative Considered**:
- **Celery**: Persistent queue, distributed workers, but adds operational complexity
- **Decision**: Start with BackgroundTasks, migrate to Celery if volume grows

### 4. Retry Strategy

**Exponential Backoff with Dead Letter Queue**

We will implement automatic retry with exponential backoff and track permanently failed emails in Neo4j.

**Configuration**:
- **Max retries**: 3 attempts
- **Initial delay**: 1 second
- **Backoff factor**: 2.0 (delays: 1s, 2s, 4s)
- **Max delay**: 60 seconds
- **Dead letter queue**: Neo4j nodes for permanent failures

**Rationale**:
- **Handles transient failures**: Network issues, temporary SMTP server problems
- **Exponential backoff**: Gives server time to recover, reduces load
- **Dead letter queue**: Permanently failed emails tracked for investigation
- **Visibility**: Failed emails don't disappear, can be manually retried

**Trade-offs**:
- Adds complexity to email client
- Delays email delivery on first failure
- Acceptable: Most emails succeed immediately, failures are rare

### 5. Development Testing

**Mailpit in Docker Compose**

We will use [Mailpit](https://github.com/axllent/mailpit) for local email testing.

**Rationale**:
- **Full SMTP server**: Real SMTP implementation, not a mock
- **Web UI**: View sent emails at http://localhost:8025
- **No external dependencies**: Runs in Docker Compose alongside Neo4j/ClickHouse
- **API access**: Can query emails programmatically for integration tests
- **No configuration**: Works out of box with no authentication

**Trade-offs**:
- Additional Docker container
- Acceptable: Lightweight container, essential for development workflow

**Alternative Considered**:
- File-based email capture: No UI, harder to inspect emails
- Third-party test services (Mailtrap): Requires account, internet connection

### 6. Audit Logging

**ClickHouse for Email Audit Logs**

We will store email send metadata in ClickHouse with 1-year retention.

**Schema**:
```sql
CREATE TABLE email_audit (
    to_email String,
    template_name String,
    subject String,
    status Enum8('sent'=1, 'failed'=2, 'skipped'=3, 'dry_run'=4),
    error_message Nullable(String),
    sent_at DateTime64(3),
    user_id Nullable(String),
    related_entity_type Nullable(String),
    related_entity_id Nullable(String)
)
ENGINE = MergeTree()
ORDER BY (sent_at, to_email)
PARTITION BY toYYYYMM(sent_at)
TTL sent_at + INTERVAL 1 YEAR
```

**Rationale**:
- **Already in stack**: ClickHouse already used for analytics
- **Time-series optimized**: Excellent performance for time-based queries
- **Built-in TTL**: Automatic retention management (1 year)
- **Efficient compression**: Large log volumes compressed automatically
- **SQL-like queries**: Easy to query for analytics and debugging

**Trade-offs**:
- ClickHouse is append-only, cannot update audit records
- Acceptable: Email audit is write-once, no updates needed

**Token Storage in Neo4j**:
- Password reset tokens and email verification tokens stored in Neo4j
- Graph relationships link tokens to User nodes
- Supports token lookup, expiry checking, usage tracking

### 7. Template System

**Jinja2 with Dual HTML/Text Templates**

We will use Jinja2 for template rendering with dedicated HTML and plain text templates.

**Structure**:
- `base.html`: Base template with Imbi branding, email-safe HTML
- `base.txt`: Plain text base template
- `{template_name}.html`: HTML version (extends base.html)
- `{template_name}.txt`: Plain text version (extends base.txt)
- Subject lines: Extracted from template comments (`{# subject: ... #}`)

**HTML-to-Text Fallback**:
- If `.txt` template missing, auto-generate from HTML
- Strip HTML tags, convert to readable plain text
- Manual `.txt` templates preferred for quality

**Rationale**:
- **Accessibility**: Plain text version for text-only email clients
- **Spam prevention**: Many spam filters check for both HTML and text parts
- **Jinja2**: Python standard for templating, mature and well-documented
- **Subject templating**: Subject lines can use variables (e.g., username)
- **Auto-generation**: Convenience for simple templates, manual for important

**Trade-offs**:
- Maintaining both HTML and text templates is extra work
- Acceptable: Critical for accessibility and deliverability

### 8. Email-Safe HTML Design

**Table-Based Layout with Inline Styles**

We will use table-based layout with inline CSS for maximum email client compatibility.

**Design Constraints**:
- Tables for layout (Gmail, Outlook require this)
- Inline CSS (many clients strip `<style>` blocks)
- No external resources (images must be data URLs or absolute URLs)
- Responsive design using media queries (for clients that support it)
- Imbi brand colors and styling

**Rationale**:
- **Compatibility**: Works across Gmail, Outlook, Apple Mail, mobile clients
- **Consistent rendering**: Inline styles not stripped
- **Professional appearance**: Branded, readable, modern design

**Trade-offs**:
- Verbose HTML (tables + inline styles)
- More complex than modern CSS
- Acceptable: Email HTML has different constraints than web HTML

### 9. Security Measures

**Token Generation and Storage**

Password reset and email verification use secure, single-use tokens.

**Token Strategy**:
- Generate: `secrets.token_urlsafe(32)` (256-bit entropy)
- Storage: Plain text in Neo4j (tokens are single-use and expire)
- Expiry: 24 hours for password reset, 7 days for email verification
- Usage tracking: Tokens marked as `used=True` after single use
- Graph relationships: Tokens linked to User nodes

**User Enumeration Prevention**:
- `/auth/forgot-password` returns 202 Accepted regardless of user existence
- Same response time whether user exists or not
- Log non-existent user attempts for security monitoring

**SMTP Security**:
- TLS/SSL support (STARTTLS on port 587 or SSL on port 465)
- Credentials stored in environment variables
- Connection timeout (30 seconds default)
- No passwords or tokens logged

**Audit Security**:
- All email sends logged to ClickHouse
- Failed attempts tracked with error messages
- No email content in logs (subject only)
- 1-year retention for compliance

## Consequences

### Positive

1. **Flexibility**: Direct SMTP works with any email provider, no vendor lock-in
2. **Simple Architecture**: No message queue infrastructure, uses FastAPI built-ins
3. **Developer Experience**: Mailpit provides excellent local testing with web UI
4. **Reliability**: Retry logic handles transient failures, DLQ tracks permanent failures
5. **Compliance**: ClickHouse audit logs provide 1-year retention for compliance
6. **Accessibility**: HTML + plain text ensures emails readable by all clients
7. **Security**: Secure token generation, user enumeration prevention, TLS support
8. **Maintainability**: Templates in version control, code review for changes
9. **Cost**: No per-email pricing, only SMTP server costs
10. **Testing**: Integration tests can verify emails via Mailpit API

### Negative

1. **Limited Scalability**: BackgroundTasks not suitable for high-volume scenarios
2. **No Built-in Analytics**: No open rate or click tracking (third-party services offer this)
3. **Manual Retry Logic**: Must implement retry ourselves (third-party handles this)
4. **Template Deployment**: Cannot edit templates without redeployment
5. **Email Loss Risk**: Emails lost if process crashes after response but before send
6. **Maintenance Burden**: Must maintain both HTML and text templates

### Mitigation Strategies

1. **Scalability**: Monitor email volume, can migrate to Celery if needed
2. **Analytics**: Add link tracking in future if needed (wrap URLs)
3. **Retry Testing**: Comprehensive tests for retry logic and failure scenarios
4. **Template Changes**: Infrequent changes expected, code review ensures quality
5. **Crash Recovery**: Log before sending, can replay from audit logs if needed
6. **Template Maintenance**: Auto-generation for simple templates, manual for critical

### Risks

1. **SMTP Server Reliability**: If SMTP server down, emails fail
   - Mitigation: Retry logic, dead letter queue, monitoring/alerting
2. **Deliverability**: Emails marked as spam without proper configuration
   - Mitigation: SPF/DKIM/DMARC configuration (deployment concern, not code)
3. **Volume Growth**: BackgroundTasks insufficient for high volume
   - Mitigation: Monitor metrics, migrate to Celery if threshold exceeded
4. **Token Compromise**: If tokens leaked, accounts vulnerable
   - Mitigation: Short expiry (24h), single-use, secure generation

### Future Enhancements

Not in scope for initial implementation:

1. **Rate Limiting**: Prevent abuse with per-user send limits
2. **Email Preferences**: Allow users to opt out of non-critical notifications
3. **Bulk Sending**: Efficient delivery to multiple recipients
4. **Template UI**: Web interface for editing templates
5. **Link Tracking**: Track email opens and link clicks
6. **Internationalization**: Multi-language email support
7. **Celery Migration**: Persistent queue for high-volume scenarios
8. **Attachment Support**: Send files with emails
9. **Inline Images**: Embed images directly in emails
10. **Advanced Retry**: Circuit breaker pattern, per-provider retry strategies

### Monitoring Recommendations

**Metrics to Track**:
- Email send success rate
- Retry attempts per email
- Dead letter queue size (growing = problem)
- Average send time
- Template rendering errors

**Alerts**:
- Email send failure rate >10%
- Dead letter queue size >100
- SMTP connection failures >5 in 5 minutes
- Template rendering errors

**Logs**:
- All sends logged with status
- Retry attempts logged
- DLQ additions logged
- Token generation and usage logged

## References

- [FastAPI BackgroundTasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)
- [Python smtplib Documentation](https://docs.python.org/3/library/smtplib.html)
- [Jinja2 Documentation](https://jinja.palletsprojects.com/)
- [Mailpit](https://github.com/axllent/mailpit)
- [Email Design Best Practices](https://www.campaignmonitor.com/css/)
- [OWASP Password Reset Guidelines](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html)
- [RFC 5321 - SMTP](https://datatracker.ietf.org/doc/html/rfc5321)
- [RFC 2046 - Multipart Email](https://datatracker.ietf.org/doc/html/rfc2046)
