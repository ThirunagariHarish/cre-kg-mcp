"""
Seed HACKATHON.PUBLIC.CRE_MARKET_INSIGHTS with synthetic but realistic CRE
market research insights.

Re-runnable: uses CREATE OR REPLACE TABLE so it resets to a deterministic state.
Reads creds from /Users/harishkumar/Projects/.env, falls back to inline.
"""

from __future__ import annotations

import json
import os
import random
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import snowflake.connector

# ---------------------------------------------------------------------------
# Credentials (env-first, inline fallback)
# ---------------------------------------------------------------------------
ENV_PATH = Path("/Users/harishkumar/Projects/.env")
if ENV_PATH.exists():
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

# Fallback inline (flagged in stdout — should be moved to env)
INLINE_FALLBACK = {
    "SNOWFLAKE_ACCOUNT": "RODBNOV-HL98478",
    "SNOWFLAKE_USER": "HARISHSERVICEACC",
    "SNOWFLAKE_PASSWORD": "RV8912xK?harish",
    "SNOWFLAKE_ROLE": "ACCOUNTADMIN",
    "SNOWFLAKE_WAREHOUSE": "COMPUTE_WH",
    "SNOWFLAKE_DATABASE": "HACKATHON",
    "SNOWFLAKE_SCHEMA": "PUBLIC",
}
USED_INLINE = False
for k, v in INLINE_FALLBACK.items():
    if not os.environ.get(k):
        os.environ[k] = v
        USED_INLINE = True

# ---------------------------------------------------------------------------
# Insight content pools
# ---------------------------------------------------------------------------
random.seed(20260505)

MARKETS = {
    "Manhattan":      ["Midtown", "Midtown South", "Downtown", "Hudson Yards", "Financial District"],
    "San Francisco":  ["SoMa", "Financial District", "Mission Bay", "Jackson Square"],
    "Austin":         ["Downtown", "East Austin", "Domain", "South Congress"],
    "Chicago":        ["The Loop", "Fulton Market", "River North", "West Loop"],
    "Dallas":         ["Uptown", "Legacy West", "Downtown", "Las Colinas"],
    "Boston":         ["Seaport", "Back Bay", "Financial District", "Cambridge"],
    "Los Angeles":    ["Downtown", "Century City", "Culver City", "Playa Vista"],
    "Seattle":        ["Downtown", "South Lake Union", "Bellevue", "Pioneer Square"],
    "Atlanta":        ["Midtown", "Buckhead", "West Midtown", "Downtown"],
    "Miami":          ["Brickell", "Wynwood", "Downtown", "Coral Gables"],
}

ASSET_CLASSES = (
    ["Office"] * 60 + ["Industrial"] * 20 + ["Retail"] * 15 + ["Mixed-Use"] * 5
)

TENANTS = [
    "Salesforce", "Amazon", "Spotify", "JPMorgan", "Meta",
    "Stripe", "Block", "Snowflake", "Google", "Microsoft",
]

SOURCES = [
    "CBRE Research", "Cushman Brief", "JLL Research", "Colliers Insights",
    "Newmark Market Report", "Avison Young Trends", "Savills Outlook",
    "Costar Analytics",
]

AUTHORS = [
    "Maria Chen",      "David Patel",      "Sarah Kim",        "Michael Ross",
    "Jennifer Liu",    "Robert Alvarez",   "Emily Thompson",   "James Okafor",
    "Priya Iyer",      "Marcus Johnson",   "Hannah Goldstein", "Diego Martinez",
    "Aisha Mohammed",  "Tom Walsh",        "Rebecca Stern",
]

# Templates: (sentiment_bucket, title_template, body_template, tag_pool)
# Using {market}/{submarket}/{tenant}/{asset} placeholders.

NEGATIVE_TEMPLATES = [
    (
        "Sublease glut deepens in {submarket} as {asset_lc} availability tops 22%",
        "Available sublease space in {market}'s {submarket} climbed for the fourth straight quarter, "
        "pushing direct landlords to slash asking rents. Class B owners are absorbing the brunt as tenants "
        "trade down to discounted second-generation suites. Concession packages now average 14 months free on a 10-year term.",
        ["sublease_pressure", "rent_decline", "tenant_favorable", "class_b"],
    ),
    (
        "Distressed {asset_lc} sale in {submarket} prints at 38% discount to 2021 basis",
        "A core {market} {asset_lc} tower traded this week at a steep discount, validating the bid-ask reset "
        "many lenders have been resisting. The seller, a pension fund, took a write-down rather than refinance into a 7%+ debt stack. "
        "Expect comparable trades to anchor the next round of appraisal markdowns.",
        ["distressed", "cap_rate_expansion", "loan_maturity", "appraisal_reset"],
    ),
    (
        "Return-to-office momentum stalls in {market} despite five-day mandates",
        "Badge-swipe data across {submarket} shows weekday utilization plateauing near 58%, well below pre-pandemic norms. "
        "Several Fortune 500 occupiers have quietly shelved expansion plans pending headcount reviews. Landlords are rethinking lobby and amenity capex assumptions.",
        ["return_to_office", "occupancy_soft", "demand_weak", "amenity_capex"],
    ),
    (
        "{tenant} marketing 240k SF of {market} space as headcount targets reset",
        "{tenant} has put a full block of its {submarket} footprint on the sublease market, the largest single posting in the submarket this year. "
        "The move follows broader cost-cutting initiatives announced last quarter. Brokers expect the listing to pressure direct asking rents in the trophy tier.",
        ["sublease_pressure", "tenant_specific", "cost_cutting", "trophy_tier"],
    ),
    (
        "Rising insurance costs squeeze {market} {asset_lc} NOI by 9% YoY",
        "Property insurance renewals in {market} jumped 22% on average this cycle, eroding net operating income across {asset_lc} portfolios. "
        "Coastal exposure and rising reinsurance costs are compounding the problem. Several owners are exploring captive structures to manage volatility.",
        ["opex_pressure", "insurance_costs", "noi_compression", "risk_management"],
    ),
    (
        "{submarket} retail vacancy ticks up as anchor tenants right-size",
        "Foot traffic recovery in {market}'s {submarket} corridor has lagged peer markets, prompting two anchor retailers to shrink their footprints by year-end. "
        "Backfill prospects skew toward experiential and food-and-beverage concepts at lower base rents. Landlords are offering aggressive TI to bridge the gap.",
        ["retail_softness", "anchor_loss", "experiential", "ti_aggressive"],
    ),
    (
        "Cap rate expansion accelerates in {market} as 10Y yields hold near 4.5%",
        "Office cap rates in {submarket} expanded another 40 bps this quarter, with bidders demanding double-digit unlevered yields on value-add deals. "
        "Equity is selectively returning, but only at deeply repriced bases. Refinancing risk remains the dominant headwind for 2021 vintage acquisitions.",
        ["cap_rate_expansion", "value_add", "refi_risk", "yield_demand"],
    ),
]

NEUTRAL_TEMPLATES = [
    (
        "{market} {asset_lc} leasing volume holds flat QoQ amid mixed signals",
        "Quarterly leasing activity in {market} landed within 3% of the prior period, with {submarket} accounting for the bulk of new deals. "
        "Tenants continue to favor shorter terms and turnkey suites. Rental rate growth remains muted across the {asset_lc} segment.",
        ["leasing_flat", "short_term_lease", "turnkey", "stable"],
    ),
    (
        "Sustainability mandates drive retrofit spend across {submarket} stock",
        "New {market} energy benchmarking rules are pushing owners to accelerate HVAC and envelope upgrades on aging {asset_lc} stock. "
        "The capex burden is significant but pencils out for trophy assets with long-duration tenancy. Class B owners face harder choices.",
        ["sustainability", "esg_capex", "retrofit", "benchmarking"],
    ),
    (
        "{market} sublease inventory plateaus after eighteen months of growth",
        "The pace of new sublease listings in {submarket} has decelerated, suggesting the worst of the giveback cycle may be behind us. "
        "Net absorption remains negative but the trajectory is improving. Watch Q3 for a clearer signal on direct rent stabilization.",
        ["sublease_plateau", "absorption_negative", "stabilization", "watchlist"],
    ),
    (
        "Cap rate spreads to Treasuries narrow as {market} pricing finds a floor",
        "Recent {asset_lc} trades in {submarket} suggest pricing has stabilized within a 25 bps band, even as financing remains expensive. "
        "Buyer pools are shallow but disciplined. Expect a slow grind higher in volume rather than a sharp rebound.",
        ["price_discovery", "cap_rate_stable", "shallow_bidder_pool", "volume_recovery"],
    ),
    (
        "Mid-market tenants drive {submarket} activity as large blocks stay quiet",
        "Deals between 5,000 and 25,000 SF accounted for 71% of {market} {asset_lc} leasing this quarter. "
        "The 100k+ SF segment remains thinly traded as enterprise occupiers extend deliberation cycles. Landlord patience is being tested but pricing has held.",
        ["mid_market", "small_deals", "enterprise_pause", "landlord_discipline"],
    ),
]

POSITIVE_TEMPLATES = [
    (
        "AI tenants drive a {asset_lc} leasing surge in {submarket}",
        "Generative AI startups and infra players have absorbed more than 1.4M SF in {market} over the past nine months, "
        "concentrated in Class A space across {submarket}. Rents on premium product are firming and concession packages are tightening. "
        "Expect this cohort to anchor the next leasing cycle.",
        ["ai_demand", "class_a", "rent_firming", "concession_compression"],
    ),
    (
        "{tenant} signs marquee {market} lease, reaffirming long-term {submarket} commitment",
        "{tenant} has executed a 15-year lease for premium space in {submarket}, one of the largest {asset_lc} deals of the cycle in {market}. "
        "The signing is a strong vote of confidence in the submarket's recovery. Brokers expect the deal to anchor adjacent leasing momentum.",
        ["tenant_specific", "long_term_lease", "trophy_tier", "anchor_deal"],
    ),
    (
        "Trophy {asset_lc} rents in {submarket} hit new high as flight-to-quality intensifies",
        "Top-tier {market} {asset_lc} buildings in {submarket} cleared a record headline rent this quarter, even as the broader market remains soft. "
        "Bifurcation between trophy and commodity stock continues to widen. Owners with Class A+ product hold meaningful pricing power.",
        ["flight_to_quality", "rent_record", "bifurcation", "pricing_power"],
    ),
    (
        "Industrial absorption in {market} outpaces deliveries for second straight quarter",
        "Net absorption of {asset_lc} space in {submarket} eclipsed new supply by 1.8M SF, tightening availability to a 3-year low. "
        "E-commerce and 3PL demand remains resilient and last-mile rents are pushing through prior peaks. Spec development pipelines are repricing higher.",
        ["industrial_demand", "absorption_strong", "last_mile", "rent_growth"],
    ),
    (
        "Sale-leaseback volume rebounds as {market} corporates monetize real estate",
        "{market} {asset_lc} sale-leaseback activity is up 45% YoY as corporate occupiers tap real estate to fund operations. "
        "Investors with long-duration capital are stepping in at attractive yields. Expect more announcements in the back half of the year.",
        ["sale_leaseback", "corporate_finance", "long_duration", "yield_attractive"],
    ),
    (
        "{tenant} expands {submarket} footprint by 180k SF in landmark renewal",
        "{tenant} not only renewed but expanded its {market} headquarters presence, adding two full floors in {submarket}. "
        "The deal cements the tenant's commitment to in-person collaboration and is being read as a bellwether for peer occupiers. Concessions were modest by current market standards.",
        ["tenant_specific", "expansion", "hq_commitment", "renewal"],
    ),
    (
        "Mixed-use {submarket} development draws institutional capital despite rate backdrop",
        "A new mixed-use project in {market}'s {submarket} closed construction financing at terms more favorable than peer deals six months ago. "
        "Institutional appetite for live-work-play product remains durable. Pre-leasing is tracking ahead of underwriting.",
        ["mixed_use", "institutional_capital", "pre_leasing", "live_work_play"],
    ),
    (
        "{market} retail experiential leasing hits multi-year high in {submarket}",
        "Experiential retail and F&B concepts drove a notable jump in {submarket} leasing volume, with deal sizes averaging 15% larger than 2024. "
        "Landlords report tighter availability on prime corner locations. The trend supports a constructive outlook on street retail rents.",
        ["experiential", "f_and_b", "rent_growth", "prime_retail"],
    ),
]

# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
def random_published_at() -> datetime:
    start = datetime(2025, 5, 1)
    end = datetime(2026, 5, 1)
    delta = end - start
    secs = random.randint(0, int(delta.total_seconds()))
    return start + timedelta(seconds=secs)


def pick_sentiment_bucket() -> str:
    r = random.random()
    if r < 0.30:
        return "neg"
    if r < 0.60:
        return "neu"
    return "pos"


def pick_impact() -> str:
    r = random.random()
    if r < 0.20:
        return "HIGH"
    if r < 0.70:
        return "MEDIUM"
    return "LOW"


def sentiment_value(bucket: str) -> float:
    if bucket == "neg":
        return round(random.uniform(-1.0, -0.2), 3)
    if bucket == "neu":
        return round(random.uniform(-0.2, 0.2), 3)
    return round(random.uniform(0.2, 1.0), 3)


def address_hint(market: str, submarket: str) -> str | None:
    if random.random() < 0.55:
        return None
    street_nums = [random.randint(100, 1899)]
    streets = {
        "Manhattan":      ["Park Avenue", "Sixth Avenue", "West 42nd Street", "Broadway", "Madison Avenue"],
        "San Francisco":  ["Mission Street", "Market Street", "Folsom Street", "Howard Street"],
        "Austin":         ["Congress Avenue", "East 6th Street", "Lavaca Street"],
        "Chicago":        ["West Wacker Drive", "North Michigan Avenue", "South LaSalle Street"],
        "Dallas":         ["McKinney Avenue", "Main Street", "Ross Avenue"],
        "Boston":         ["Boylston Street", "Seaport Boulevard", "State Street"],
        "Los Angeles":    ["South Figueroa Street", "Wilshire Boulevard", "Santa Monica Boulevard"],
        "Seattle":        ["Westlake Avenue North", "Fifth Avenue", "Boren Avenue"],
        "Atlanta":        ["Peachtree Street NE", "West Peachtree Street", "Ponce de Leon Avenue"],
        "Miami":          ["Brickell Avenue", "Biscayne Boulevard", "South Miami Avenue"],
    }
    street = random.choice(streets.get(market, ["Main Street"]))
    return f"{street_nums[0]} {street}"


def build_row(
    sentiment_bucket: str,
    impact: str,
    market: str,
    submarket: str,
    asset: str,
    tenant: str | None,
    published_at: datetime,
    daily_counter: int,
) -> dict[str, Any]:
    if sentiment_bucket == "pos":
        pool = POSITIVE_TEMPLATES
    elif sentiment_bucket == "neg":
        pool = NEGATIVE_TEMPLATES
    else:
        pool = NEUTRAL_TEMPLATES

    # If a tenant is required, prefer templates that mention {tenant}
    if tenant:
        tenant_pool = [t for t in pool if "{tenant}" in t[0] or "{tenant}" in t[1]]
        if tenant_pool:
            pool = tenant_pool

    title_t, body_t, base_tags = random.choice(pool)

    asset_lc_map = {
        "Office": "office",
        "Industrial": "industrial",
        "Retail": "retail",
        "Mixed-Use": "mixed-use",
    }
    asset_lc = asset_lc_map[asset]

    fmt = {
        "market": market,
        "submarket": submarket,
        "asset": asset,
        "asset_lc": asset_lc,
        "tenant": tenant or "",
    }
    title = title_t.format(**fmt)
    body = body_t.format(**fmt)

    # Tags: base + 1-2 contextual
    extra_pool = [
        market.lower().replace(" ", "_"),
        submarket.lower().replace(" ", "_"),
        asset_lc.replace("-", "_"),
    ]
    tags = list(dict.fromkeys(base_tags + random.sample(extra_pool, k=min(2, len(extra_pool)))))
    # Trim to 3-6
    tags = tags[: random.randint(3, 6)]

    insight_id = f"INS-{published_at.strftime('%Y%m%d')}-{daily_counter:03d}"

    return {
        "INSIGHT_ID":    insight_id,
        "TITLE":         title,
        "BODY":          body,
        "SOURCE":        random.choice(SOURCES),
        "AUTHOR":        random.choice(AUTHORS),
        "PUBLISHED_AT":  published_at,
        "MARKET":        market,
        "SUBMARKET":     submarket,
        "ASSET_CLASS":   asset,
        "TENANT_NAME":   tenant,
        "PROPERTY_HINT": address_hint(market, submarket),
        "RAW_TAGS":      tags,
        "SENTIMENT":     sentiment_value(sentiment_bucket),
        "IMPACT":        impact,
    }


def generate_rows(n: int = 50) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    daily_counters: dict[str, int] = defaultdict(int)

    # Pre-pick global distributions to ensure constraints
    market_list = list(MARKETS.keys())
    # Ensure each of the 10 markets gets >= 1 row (>=8 required, we cover all 10)
    forced_markets = market_list.copy()
    random.shuffle(forced_markets)

    # Ensure 6 tenant-specific rows (within 5-8 range)
    tenant_indexes = set(random.sample(range(n), 6))

    for i in range(n):
        # Market: first 10 rows guarantee coverage of all markets
        market = forced_markets[i] if i < len(forced_markets) else random.choice(market_list)
        submarket = random.choice(MARKETS[market])
        asset = random.choice(ASSET_CLASSES)
        sentiment_bucket = pick_sentiment_bucket()
        impact = pick_impact()
        tenant = random.choice(TENANTS) if i in tenant_indexes else None
        # Tenant-specific rows skew positive/negative away from neutral
        if tenant and sentiment_bucket == "neu":
            sentiment_bucket = random.choice(["pos", "neg"])

        published_at = random_published_at()
        day_key = published_at.strftime("%Y%m%d")
        daily_counters[day_key] += 1
        row = build_row(
            sentiment_bucket=sentiment_bucket,
            impact=impact,
            market=market,
            submarket=submarket,
            asset=asset,
            tenant=tenant,
            published_at=published_at,
            daily_counter=daily_counters[day_key],
        )
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Snowflake I/O
# ---------------------------------------------------------------------------
DDL = """
CREATE OR REPLACE TABLE HACKATHON.PUBLIC.CRE_MARKET_INSIGHTS (
  INSIGHT_ID         VARCHAR(64)    NOT NULL,
  TITLE              VARCHAR(500)   NOT NULL,
  BODY               VARCHAR(8000),
  SOURCE             VARCHAR(200),
  AUTHOR             VARCHAR(200),
  PUBLISHED_AT       TIMESTAMP_NTZ  NOT NULL,
  INGESTED_AT        TIMESTAMP_NTZ  DEFAULT CURRENT_TIMESTAMP(),
  MARKET             VARCHAR(100),
  SUBMARKET          VARCHAR(100),
  ASSET_CLASS        VARCHAR(50),
  TENANT_NAME        VARCHAR(200),
  PROPERTY_HINT      VARCHAR(500),
  RAW_TAGS           ARRAY,
  SENTIMENT          NUMBER(5,3),
  IMPACT             VARCHAR(20),
  PRIMARY KEY (INSIGHT_ID)
)
"""

INSERT_SQL = """
INSERT INTO HACKATHON.PUBLIC.CRE_MARKET_INSIGHTS
  (INSIGHT_ID, TITLE, BODY, SOURCE, AUTHOR, PUBLISHED_AT,
   MARKET, SUBMARKET, ASSET_CLASS, TENANT_NAME, PROPERTY_HINT,
   RAW_TAGS, SENTIMENT, IMPACT)
SELECT
  column1, column2, column3, column4, column5, column6,
  column7, column8, column9, column10, column11,
  PARSE_JSON(column12), column13, column14
FROM VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def main() -> None:
    if USED_INLINE:
        print("[warn] One or more credentials missing from .env; using inline fallback. "
              "Move all SNOWFLAKE_* vars to /Users/harishkumar/Projects/.env before re-running in CI.")

    rows = generate_rows(50)

    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        role=os.environ["SNOWFLAKE_ROLE"],
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        database=os.environ["SNOWFLAKE_DATABASE"],
        schema=os.environ["SNOWFLAKE_SCHEMA"],
        authenticator="snowflake",
    )
    try:
        cur = conn.cursor()
        try:
            print("[step] Creating table HACKATHON.PUBLIC.CRE_MARKET_INSIGHTS")
            cur.execute(DDL)

            print(f"[step] Inserting {len(rows)} rows")
            payload = [
                (
                    r["INSIGHT_ID"],
                    r["TITLE"],
                    r["BODY"],
                    r["SOURCE"],
                    r["AUTHOR"],
                    r["PUBLISHED_AT"],
                    r["MARKET"],
                    r["SUBMARKET"],
                    r["ASSET_CLASS"],
                    r["TENANT_NAME"],
                    r["PROPERTY_HINT"],
                    json.dumps(r["RAW_TAGS"]),
                    r["SENTIMENT"],
                    r["IMPACT"],
                )
                for r in rows
            ]
            cur.executemany(INSERT_SQL, payload)

            print("[step] Verifying row count")
            cur.execute("SELECT COUNT(*) FROM HACKATHON.PUBLIC.CRE_MARKET_INSIGHTS")
            count = cur.fetchone()[0]
            print(f"[result] row_count={count}")

            print("[step] Sampling rows (positive, negative, tenant-specific)")
            sample_sql = """
                (SELECT 'positive' AS bucket, INSIGHT_ID, TITLE, MARKET, ASSET_CLASS,
                        TENANT_NAME, SENTIMENT, IMPACT, PUBLISHED_AT
                 FROM HACKATHON.PUBLIC.CRE_MARKET_INSIGHTS
                 WHERE SENTIMENT > 0.3 ORDER BY SENTIMENT DESC LIMIT 1)
                UNION ALL
                (SELECT 'negative', INSIGHT_ID, TITLE, MARKET, ASSET_CLASS,
                        TENANT_NAME, SENTIMENT, IMPACT, PUBLISHED_AT
                 FROM HACKATHON.PUBLIC.CRE_MARKET_INSIGHTS
                 WHERE SENTIMENT < -0.3 ORDER BY SENTIMENT ASC LIMIT 1)
                UNION ALL
                (SELECT 'tenant', INSIGHT_ID, TITLE, MARKET, ASSET_CLASS,
                        TENANT_NAME, SENTIMENT, IMPACT, PUBLISHED_AT
                 FROM HACKATHON.PUBLIC.CRE_MARKET_INSIGHTS
                 WHERE TENANT_NAME IS NOT NULL ORDER BY PUBLISHED_AT DESC LIMIT 1)
            """
            cur.execute(sample_sql)
            cols = [c[0] for c in cur.description]
            print("[result] sample_rows:")
            for row in cur.fetchall():
                rec = dict(zip(cols, row))
                print(json.dumps(rec, default=str, indent=2))
        finally:
            cur.close()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
