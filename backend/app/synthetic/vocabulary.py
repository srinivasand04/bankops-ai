"""Incident wording per category: templates + random entities (error codes, hosts, queues, jobs).

Each category has its own words so text classification has something to learn. A share of
incidents (AMBIGUOUS_TEXT_RATE in generator.py) borrows wording from a *confusable* category, so
the task is not trivially perfect - exactly what happens in real ticket queues.
"""

TITLES: dict[str, tuple[str, ...]] = {
    "APPLICATION": (
        "{app}: NullPointerException in {component} after request spike",
        "{app} feature {component} returns wrong results for some customers",
        "{app} service {component} restarting in a loop",
        "Unhandled exception in {app} {component} module",
    ),
    "DATABASE": (
        "{app}: database connection errors {ora}",
        "Deadlocks detected on table {table} in {app}",
        "{app} database tablespace {table} almost full",
        "Slow SQL on {table} causing lock waits in {app}",
    ),
    "INFRASTRUCTURE": (
        "Host {host} unresponsive - {app} degraded",
        "Disk full on {host} affecting {app}",
        "Storage latency high on {host} cluster for {app}",
        "VM {host} rebooted unexpectedly ({app})",
    ),
    "NETWORK": (
        "Packet loss between {dc} and {dc2} affecting {app}",
        "Load balancer {lb} health checks failing for {app}",
        "DNS resolution failures for {app} endpoints",
        "Firewall blocking traffic from {host} to {partner}",
    ),
    "SECURITY": (
        "Suspicious login pattern detected on {app}",
        "Expired TLS certificate on {app} endpoint",
        "WAF blocking legitimate {app} traffic",
        "Vulnerability scanner flags {component} in {app}",
    ),
    "BATCH_PROCESSING": (
        "Batch job {job} failed on {app}",
        "{job} overran its window on {app}",
        "{job} stuck in WAIT status ({app})",
        "Dependent jobs delayed after {job} abend",
    ),
    "API_INTEGRATION": (
        "{app} API returning HTTP 500 on {endpoint}",
        "Timeouts calling {partner} API from {app}",
        "{app} {endpoint} responses failing schema validation",
        "Integration errors between {app} and {partner}",
    ),
    "THIRD_PARTY_SERVICE": (
        "{partner} service degraded - {app} impacted",
        "Vendor {partner} outage affecting {app}",
        "{partner} rejecting requests from {app}",
        "Late file delivery from {partner} to {app}",
    ),
    "AUTHENTICATION": (
        "Customers unable to log in to {app}",
        "{app} token validation failing after key rotation",
        "SSO redirect loop on {app}",
        "MFA codes not delivered for {app} logins",
    ),
    "PERFORMANCE": (
        "{app} response times above {seconds} s",
        "High latency on {app} {endpoint}",
        "{app} CPU saturation during peak",
        "Slow page loads in {app}",
    ),
    "DATA_PROCESSING": (
        "Data mismatch between {app} and {partner} extract",
        "Duplicate records in {app} {table} feed",
        "{app} file {file} rejected - format error",
        "Missing records in {app} daily extract",
    ),
}

SYMPTOMS: dict[str, tuple[str, ...]] = {
    "APPLICATION": ("Stack traces show {exception} in {component}.", "Error logs spiked to {count} per minute after the last request burst."),
    "DATABASE": ("Application logs show {ora}.", "Active sessions are close to the limit and lock waits exceed {seconds} s."),
    "INFRASTRUCTURE": ("Monitoring lost heartbeat from {host}.", "Disk utilisation on {host} is at {pct}%."),
    "NETWORK": ("Ping loss of {pct}% observed between data centres.", "Load balancer {lb} marks {count} members down."),
    "SECURITY": ("SOC raised alert {alert} for {app}.", "Certificate for {endpoint} expired at {time}."),
    "BATCH_PROCESSING": ("{job} ended NOTOK with exit code {exit}.", "{job} has been running {count} minutes longer than usual."),
    "API_INTEGRATION": ("HTTP 5xx rate on {endpoint} reached {pct}%.", "Calls to {partner} time out after {seconds} s."),
    "THIRD_PARTY_SERVICE": ("{partner} status page reports degraded service.", "Vendor ticket {ticket} opened with {partner}."),
    "AUTHENTICATION": ("Login failure rate at {pct}%.", "Token validation errors: key id not found in JWKS cache."),
    "PERFORMANCE": ("p95 latency rose to {seconds} s.", "CPU on {host} at {pct}% during peak hours."),
    "DATA_PROCESSING": ("{count} records failed validation in file {file}.", "Totals differ by {count} items between source and target."),
}

# Categories whose wording is easily confused (source of the deliberate text ambiguity)
CONFUSABLE: dict[str, tuple[str, ...]] = {
    "APPLICATION": ("PERFORMANCE", "API_INTEGRATION"),
    "DATABASE": ("PERFORMANCE", "BATCH_PROCESSING"),
    "INFRASTRUCTURE": ("NETWORK", "PERFORMANCE"),
    "NETWORK": ("INFRASTRUCTURE", "API_INTEGRATION"),
    "SECURITY": ("AUTHENTICATION",),
    "BATCH_PROCESSING": ("DATA_PROCESSING", "DATABASE"),
    "API_INTEGRATION": ("THIRD_PARTY_SERVICE", "APPLICATION"),
    "THIRD_PARTY_SERVICE": ("API_INTEGRATION",),
    "AUTHENTICATION": ("SECURITY", "APPLICATION"),
    "PERFORMANCE": ("DATABASE", "INFRASTRUCTURE"),
    "DATA_PROCESSING": ("BATCH_PROCESSING",),
}

RESOLUTIONS: dict[str, tuple[str, ...]] = {
    "APPLICATION": ("Hotfix deployed for {component}.", "Service restarted and faulty feature toggle disabled."),
    "DATABASE": ("Long-running sessions killed and pool resized.", "Index rebuilt and statistics refreshed on {table}."),
    "INFRASTRUCTURE": ("Host {host} replaced and workload rebalanced.", "Disk extended and log rotation fixed."),
    "NETWORK": ("Faulty link failed over to secondary path.", "Firewall rule restored for {partner}."),
    "SECURITY": ("Certificate renewed and deployed.", "WAF rule tuned to allow legitimate traffic."),
    "BATCH_PROCESSING": ("{job} rerun after fixing input data.", "Job dependency corrected and batch rerun."),
    "API_INTEGRATION": ("Retry and timeout settings corrected for {partner}.", "API deployment rolled back."),
    "THIRD_PARTY_SERVICE": ("{partner} resolved the issue on their side.", "Traffic switched to backup provider."),
    "AUTHENTICATION": ("JWKS cache refreshed and config fixed.", "SSO configuration corrected."),
    "PERFORMANCE": ("Capacity added and slow queries tuned.", "Cache resized and hot keys warmed."),
    "DATA_PROCESSING": ("Corrupt records quarantined and file reprocessed.", "Mapping rule fixed and extract regenerated."),
}

ENTITIES: dict[str, tuple[str, ...]] = {
    "component": ("limits", "statements", "beneficiaries", "fx-quote", "standing-orders", "notifications", "onboarding"),
    "table": ("ACCOUNT_TXN", "CUSTOMER", "LEDGER_ENTRY", "PAYMENT_ORDER", "CARD_AUTH", "GL_BALANCE"),
    "ora": ("ORA-12519", "ORA-00060", "ORA-01555", "ORA-04031", "ORA-12170"),
    "exception": ("NullPointerException", "IllegalStateException", "TimeoutException", "OutOfMemoryError"),
    "dc": ("DC-North",), "dc2": ("DC-South",),
    "lb": ("lb-prod-01", "lb-prod-02", "lb-dmz-01"),
    "partner": ("card scheme gateway", "SWIFT gateway", "identity provider", "PDF vendor", "market data vendor",
                "sanctions list vendor", "push notification provider", "credit bureau"),
    "endpoint": ("/payments/authorise", "/accounts/{id}/balance", "/auth/token", "/transactions/export", "/cards/authorise"),
    "file": ("PAY_EXTRACT.csv", "GL_POSTINGS.dat", "SANCTIONS_LIST.xml", "STATEMENTS.zip"),
    "alert": ("SOC-1182", "SOC-2210", "SOC-3045"),
    "ticket": ("VND-7781", "VND-8120", "VND-9034"),
}
