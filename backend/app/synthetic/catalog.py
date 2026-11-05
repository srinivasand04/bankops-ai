"""Applications, dependencies, teams and recurring problems of the large synthetic bank.

The first five applications are the demo environment's (same codes, names and tiers); the dataset
manifest sets `reuse_applications`, so loading next to the demo dataset references them.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AppSpec:
    code: str
    name: str
    tier: str  # TIER_1 / TIER_2 / TIER_3
    owner_team: str
    stack: str
    description: str
    # Relative incident volume and the category mix this application tends to produce
    incident_weight: float
    categories: dict[str, float]
    # Hourly metric (always) and an optional 4-hourly second metric
    metric: tuple[str, str, float]  # (name, unit, baseline)
    metric2: tuple[str, str, float] | None = None
    batch_jobs: tuple[str, ...] = ()
    hosts: tuple[str, ...] = field(default=())


APPS: tuple[AppSpec, ...] = (
    # ---- the demo environment's five applications -------------------------------------------
    AppSpec("PAY", "Payment Processing", "TIER_1", "Payments Production Support",
            "Java 21 / Spring Boot REST API, PostgreSQL, Kafka",
            "Processes customer payments (domestic transfers, card settlements) via REST API.", 1.4,
            {"API_INTEGRATION": 3, "APPLICATION": 3, "DATABASE": 2, "PERFORMANCE": 2, "THIRD_PARTY_SERVICE": 1, "NETWORK": 1},
            ("http_5xx_rate_pct", "%", 0.3), ("p95_latency_ms", "ms", 350), hosts=("pay-api-01", "pay-api-02", "pay-batch-01")),
    AppSpec("CBS", "Core Banking", "TIER_1", "Core Banking Support",
            "Core banking package, Oracle Database, IBM MQ",
            "System of record for customer accounts, balances and ledger postings.", 1.1,
            {"DATABASE": 4, "BATCH_PROCESSING": 2, "INFRASTRUCTURE": 2, "PERFORMANCE": 2, "APPLICATION": 1},
            ("db_cpu_pct", "%", 40), ("ledger_posting_latency_ms", "ms", 45), batch_jobs=("EOD_INTEREST", "EOD_LEDGER_CLOSE"),
            hosts=("cbs-db-01", "cbs-db-02", "cbs-app-01")),
    AppSpec("CUS", "Customer Services", "TIER_2", "Digital Channels Support",
            "Python FastAPI microservice, Redis cache, OAuth2 / SSO",
            "API layer that provides customer, account and transaction status information to channels.", 1.0,
            {"API_INTEGRATION": 3, "AUTHENTICATION": 2, "PERFORMANCE": 2, "APPLICATION": 2, "THIRD_PARTY_SERVICE": 1},
            ("api_error_rate_pct", "%", 0.5), hosts=("cus-api-01", "cus-api-02")),
    AppSpec("REC", "Transaction Reconciliation", "TIER_2", "Reconciliation Operations",
            "Python batch jobs, SQL, Control-M scheduler",
            "Reconciles payment transactions against core banking ledger postings.", 0.8,
            {"BATCH_PROCESSING": 5, "DATA_PROCESSING": 3, "DATABASE": 1},
            ("unmatched_items", "count", 15), batch_jobs=("RECON_INTRADAY_PAY", "RECON_EOD_PAY"), hosts=("rec-batch-01",)),
    AppSpec("RDW", "Reporting & Data Warehouse", "TIER_3", "Data Platform Support",
            "SQL data warehouse, ETL pipelines, BI dashboards",
            "Generates financial, regulatory and operational reports.", 0.8,
            {"PERFORMANCE": 3, "DATA_PROCESSING": 3, "BATCH_PROCESSING": 2, "DATABASE": 1},
            ("dw_cpu_pct", "%", 45), batch_jobs=("ETL_AGG_DAILY", "LIQUIDITY_REPORT"), hosts=("dw-node-01", "dw-node-02")),
    # ---- additional applications -------------------------------------------------------------
    AppSpec("CARDS", "Cards Authorisation", "TIER_1", "Cards Production Support",
            "C++ authorisation engine, HSM cluster, card scheme gateways",
            "Authorises card transactions in real time against limits and fraud rules.", 1.2,
            {"API_INTEGRATION": 2, "THIRD_PARTY_SERVICE": 2, "NETWORK": 2, "SECURITY": 1, "PERFORMANCE": 2, "APPLICATION": 1},
            ("auth_decline_rate_pct", "%", 2.0), ("auth_latency_ms", "ms", 120), hosts=("cards-auth-01", "cards-auth-02", "hsm-01")),
    AppSpec("OLB", "Online Banking", "TIER_1", "Digital Channels Support",
            "React web front end, Java BFF, CDN",
            "Customer web banking portal.", 1.1,
            {"APPLICATION": 3, "AUTHENTICATION": 2, "PERFORMANCE": 2, "NETWORK": 1, "SECURITY": 1},
            ("login_success_rate_pct", "%", 98.5), hosts=("olb-web-01", "olb-bff-01")),
    AppSpec("MOB", "Mobile Banking", "TIER_1", "Mobile Channels Support",
            "iOS / Android apps, mobile API gateway, push notification service",
            "Customer mobile banking apps and their API gateway.", 1.1,
            {"APPLICATION": 3, "AUTHENTICATION": 2, "API_INTEGRATION": 2, "THIRD_PARTY_SERVICE": 1, "PERFORMANCE": 1},
            ("app_crash_rate_pct", "%", 0.4), ("gateway_latency_ms", "ms", 180), hosts=("mob-gw-01", "mob-gw-02")),
    AppSpec("AML", "AML Screening", "TIER_1", "Financial Crime Technology",
            "Rules engine, sanctions list service, case management",
            "Screens payments and customers against sanctions and AML rules.", 0.7,
            {"DATA_PROCESSING": 3, "BATCH_PROCESSING": 2, "THIRD_PARTY_SERVICE": 2, "PERFORMANCE": 1, "SECURITY": 1},
            ("screening_queue_depth", "count", 40), batch_jobs=("SANCTIONS_LIST_LOAD",), hosts=("aml-engine-01",)),
    AppSpec("TRS", "Treasury", "TIER_2", "Treasury Technology",
            "Trading and liquidity platform, market data feeds",
            "Liquidity management, FX and money-market dealing.", 0.6,
            {"THIRD_PARTY_SERVICE": 3, "DATA_PROCESSING": 2, "APPLICATION": 2, "NETWORK": 1},
            ("market_data_lag_s", "s", 1.5), hosts=("trs-app-01", "mdf-01")),
    AppSpec("GL", "General Ledger", "TIER_2", "Finance Systems Support",
            "ERP general ledger module, Oracle Database",
            "Consolidates postings from core systems into the bank's general ledger.", 0.6,
            {"BATCH_PROCESSING": 3, "DATABASE": 2, "DATA_PROCESSING": 2, "APPLICATION": 1},
            ("gl_posting_backlog", "count", 100), batch_jobs=("GL_POST", "GL_MONTH_END"), hosts=("gl-db-01", "gl-app-01")),
    AppSpec("BATCH", "Batch Scheduler", "TIER_2", "Infrastructure Operations",
            "Control-M enterprise scheduler, agents on all batch hosts",
            "Schedules and monitors the bank's overnight and intraday batch.", 0.7,
            {"BATCH_PROCESSING": 4, "INFRASTRUCTURE": 3, "NETWORK": 1},
            ("jobs_failed_per_hour", "count", 1.0), batch_jobs=("CTM_NIGHTLY_CYCLE",), hosts=("ctm-server-01", "ctm-agent-07")),
)

APP_BY_CODE = {a.code: a for a in APPS}

# (application, depends_on, type, critical). Demo pairs are skipped by the loader if already present.
DEPENDENCIES: tuple[tuple[str, str, str, bool], ...] = (
    ("PAY", "CBS", "API", True),
    ("CUS", "PAY", "API", True),
    ("CUS", "CBS", "API", True),
    ("REC", "PAY", "BATCH_FEED", True),
    ("REC", "CBS", "BATCH_FEED", True),
    ("RDW", "REC", "BATCH_FEED", False),
    ("RDW", "CBS", "BATCH_FEED", False),
    ("OLB", "CUS", "API", True),
    ("MOB", "CUS", "API", True),
    ("OLB", "PAY", "API", True),
    ("MOB", "PAY", "API", True),
    ("CARDS", "CBS", "API", True),
    ("PAY", "AML", "API", True),
    ("CARDS", "AML", "API", False),
    ("AML", "CBS", "DATABASE", False),
    ("GL", "CBS", "BATCH_FEED", True),
    ("GL", "REC", "BATCH_FEED", False),
    ("TRS", "GL", "BATCH_FEED", False),
    ("RDW", "GL", "BATCH_FEED", False),
    ("REC", "BATCH", "INFRASTRUCTURE", True),
    ("GL", "BATCH", "INFRASTRUCTURE", True),
    ("CBS", "BATCH", "INFRASTRUCTURE", True),
)

# Specialist teams that receive some categories instead of the owning application team (routing label)
SPECIALIST_TEAMS: dict[str, str] = {
    "NETWORK": "Network Operations",
    "INFRASTRUCTURE": "Infrastructure Operations",
    "SECURITY": "Security Operations",
    "DATABASE": "Database Engineering",
}
SPECIALIST_ROUTING_RATE = 0.55  # share of those categories routed to the specialist team

ENGINEERS: dict[str, tuple[str, ...]] = {
    "Payments Production Support": ("a.patel", "m.rossi", "k.owusu"),
    "Core Banking Support": ("d.okafor", "s.iyer"),
    "Digital Channels Support": ("l.moreau", "p.nair"),
    "Reconciliation Operations": ("j.chen", "r.alvarez"),
    "Data Platform Support": ("m.tanaka", "e.kowalski"),
    "Cards Production Support": ("h.schmidt", "y.kim"),
    "Mobile Channels Support": ("t.okoro", "c.lopez"),
    "Financial Crime Technology": ("n.fischer", "b.adeyemi"),
    "Treasury Technology": ("g.rossi", "f.dubois"),
    "Finance Systems Support": ("v.petrova", "o.hassan"),
    "Infrastructure Operations": ("s.novak", "i.horvat"),
    "Network Operations": ("w.zhang", "a.berg"),
    "Security Operations": ("q.ahmed", "l.jansen"),
    "Database Engineering": ("u.mehta", "z.costa"),
}


@dataclass(frozen=True)
class Problem:
    """A recurring root cause: the same fault repeats on the same application (clustering signal)."""

    key: str  # PRB-xxx, written into the confirmed root cause so clusters can be compared
    app: str
    category: str
    title: str
    description: str
    root_cause: str
    occurrences: int  # at scale 1.0 over 12 months


PROBLEMS: tuple[Problem, ...] = (
    Problem("PRB-001", "CBS", "BATCH_PROCESSING", "EOD_INTEREST batch overruns its window",
            "EOD_INTEREST ran past 02:00 because the interest accrual step waited on locked ACCOUNT_TXN rows.",
            "Row-lock contention between EOD_INTEREST and the statement extract job", 28),
    Problem("PRB-002", "PAY", "DATABASE", "Payment API connection pool exhausted",
            "Requests to POST /payments/authorise fail with 'Connection is not available, request timed out'.",
            "Connection pool too small for peak load after traffic growth", 24),
    Problem("PRB-003", "REC", "BATCH_PROCESSING", "RECON_INTRADAY_PAY fails on malformed currency code",
            "The intraday reconciliation aborts when the payment extract contains an invalid ISO currency code.",
            "Payment extract does not validate currency codes before export", 26),
    Problem("PRB-004", "CARDS", "THIRD_PARTY_SERVICE", "Card scheme gateway timeouts during peak",
            "Authorisation requests to the card scheme gateway time out at lunchtime peaks.",
            "Scheme gateway connection limit too low for peak authorisation volume", 22),
    Problem("PRB-005", "OLB", "AUTHENTICATION", "Login failures after identity provider key rotation",
            "Customers get 'session expired' right after login; tokens signed with the new key are rejected.",
            "Online banking caches identity provider signing keys for 24 h", 14),
    Problem("PRB-006", "MOB", "API_INTEGRATION", "Push notification provider rejects requests",
            "Push notifications fail with HTTP 429 from the notification provider.",
            "Notification batch exceeds the provider's per-minute quota", 18),
    Problem("PRB-007", "GL", "DATABASE", "GL_POST fails with ORA-01555 snapshot too old",
            "The nightly GL_POST job fails with ORA-01555 when month-end volumes are high.",
            "Undo retention too short for month-end posting volumes", 16),
    Problem("PRB-008", "RDW", "PERFORMANCE", "Reporting queries slow during ETL overlap",
            "Finance dashboard queries take over 60 s while ETL_AGG_DAILY runs.",
            "ETL_AGG_DAILY scheduled inside the business reporting window", 26),
    Problem("PRB-009", "AML", "DATA_PROCESSING", "Sanctions list load delayed",
            "SANCTIONS_LIST_LOAD finishes late, so screening uses yesterday's list for several hours.",
            "Vendor sanctions file arrives late and the load has no retry schedule", 14),
    Problem("PRB-010", "BATCH", "INFRASTRUCTURE", "Control-M agent disconnects on batch host",
            "Control-M agent on ctm-agent-07 loses connection; dependent jobs stay in WAIT state.",
            "Agent host runs out of file descriptors after long uptime", 20),
    Problem("PRB-011", "CUS", "PERFORMANCE", "Redis cache evictions slow account summary",
            "Account summary API latency rises when the Redis cache evicts hot keys.",
            "Redis maxmemory too small for the account summary working set", 18),
    Problem("PRB-012", "TRS", "THIRD_PARTY_SERVICE", "Market data feed stale",
            "The FX market data feed stops updating; dealers see stale rates.",
            "Market data vendor drops idle sessions without heartbeat", 14),
)
