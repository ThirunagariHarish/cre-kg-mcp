import asyncio, json, os
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv("/Users/harishkumar/Projects/.env")

d = GraphDatabase.driver(os.getenv("NEO4J_URI"), auth=(os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASSWORD")))

async def main():
    from mcp_server.tools.health_check import run_health_check
    from mcp_server.tools.find_matching_properties_for_insight import run_find_matching_properties_for_insight
    from mcp_server.tools.suggest_next_best_actions_for_deal import run_suggest_next_best_actions
    from mcp_server.tools.recommend_broker_for_deal import run_recommend_broker_for_deal

    print("=" * 70)
    print("HEALTH CHECK")
    print("=" * 70)
    r = await run_health_check(d)
    print(json.dumps(r, indent=2, default=str)[:1500])

    print()
    print("=" * 70)
    print("Q1: find_matching_properties_for_insight (Microsoft Boston insight)")
    print("=" * 70)
    r = await run_find_matching_properties_for_insight(d, insight_id="INS-20260319-001")
    print(json.dumps(r, indent=2, default=str)[:2500])

    print()
    print("=" * 70)
    print("Q2: suggest_next_best_actions_for_deal (PUR-0000001)")
    print("=" * 70)
    r = await run_suggest_next_best_actions(d, pursuit_id="PUR-0000001")
    print(json.dumps(r, indent=2, default=str)[:2500])

    print()
    print("=" * 70)
    print("Q3: recommend_broker_for_deal (Manhattan Office)")
    print("=" * 70)
    r = await run_recommend_broker_for_deal(d, market="manhattan", asset_class="office", service_line="leasing")
    print(json.dumps(r, indent=2, default=str)[:2500])

asyncio.run(main())
d.close()
