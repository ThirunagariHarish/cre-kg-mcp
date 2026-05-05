#!/usr/bin/env bash
# scripts/demo.sh — CRE Knowledge Graph MCP Demo Setup
#
# Usage: bash scripts/demo.sh
#
# This script:
#   1. Starts Neo4j + GDS via docker-compose
#   2. Runs backfill if the graph is empty
#   3. Starts the insight ingester in the background
#   4. Starts the ML refresh worker in the background
#   5. Polls until all required enrichments are in place
#   6. Prints the "Ready to demo" message with sample Claude prompts

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'  # No Colour

info()    { echo -e "${GREEN}[demo]${NC} $*"; }
warning() { echo -e "${YELLOW}[demo]${NC} $*"; }
error()   { echo -e "${RED}[demo]${NC} $*"; }

# ---------------------------------------------------------------------------
# 1. Start Neo4j + GDS
# ---------------------------------------------------------------------------
info "Starting Neo4j + GDS via docker-compose..."
docker compose up -d

info "Waiting for Neo4j to become healthy (up to 3 minutes)..."
attempts=0
max_attempts=36
until docker compose exec -T neo4j cypher-shell -u neo4j -p hackathon_local_only \
    "CALL gds.version() YIELD version RETURN version" > /dev/null 2>&1; do
    attempts=$((attempts + 1))
    if [ "$attempts" -ge "$max_attempts" ]; then
        error "Neo4j did not become healthy within 3 minutes. Check 'docker compose logs neo4j'."
        exit 1
    fi
    echo -n "."
    sleep 5
done
echo ""
info "Neo4j is healthy."

# ---------------------------------------------------------------------------
# 2. Backfill if graph is empty
# ---------------------------------------------------------------------------
BROKER_COUNT=$(docker compose exec -T neo4j cypher-shell -u neo4j -p hackathon_local_only \
    "MATCH (b:Broker) RETURN count(b) AS cnt" --format plain 2>/dev/null \
    | grep -E '^[0-9]+$' | head -1 || echo "0")

if [ "${BROKER_COUNT:-0}" -eq 0 ]; then
    info "Graph appears empty. Running backfill (this may take ~2 minutes)..."
    .venv/bin/python scripts/backfill.py
    info "Backfill complete."
else
    info "Graph already populated ($BROKER_COUNT Broker nodes). Skipping backfill."
fi

# ---------------------------------------------------------------------------
# 3. Start the streaming ingester in the background
# ---------------------------------------------------------------------------
info "Starting insight ingester in background..."
.venv/bin/python -m ingester.streaming > /tmp/cre_ingester.log 2>&1 &
INGESTER_PID=$!
info "Ingester PID: $INGESTER_PID (logs: /tmp/cre_ingester.log)"

# ---------------------------------------------------------------------------
# 4. Start the ML refresh worker in the background
# ---------------------------------------------------------------------------
info "Starting ML refresh worker in background..."
.venv/bin/python -m ml.refresh > /tmp/cre_ml.log 2>&1 &
ML_PID=$!
info "ML worker PID: $ML_PID (logs: /tmp/cre_ml.log)"

# ---------------------------------------------------------------------------
# 5. Poll for enrichment readiness
# ---------------------------------------------------------------------------
info "Waiting for enrichments to be ready (up to 5 minutes)..."

# Helper: run a Cypher count query
cypher_count() {
    local query="$1"
    docker compose exec -T neo4j cypher-shell -u neo4j -p hackathon_local_only \
        "$query" --format plain 2>/dev/null \
        | grep -E '^[0-9]+$' | head -1 || echo "0"
}

max_wait=300  # 5 minutes
elapsed=0
step=10

while [ "$elapsed" -lt "$max_wait" ]; do
    INSIGHT_CNT=$(cypher_count "MATCH (i:Insight) RETURN count(i) AS cnt")
    EMBED_CNT=$(cypher_count "MATCH (b:Broker) WHERE b.node2vec_embedding IS NOT NULL RETURN count(b) AS cnt")
    COMM_CNT=$(cypher_count "MATCH (b:Broker) WHERE b.community_id IS NOT NULL RETURN count(b) AS cnt")
    PRED_CNT=$(cypher_count "MATCH (pl:PredictedLink) RETURN count(pl) AS cnt")

    echo -n "  Insights: ${INSIGHT_CNT}/50+  |  Embeddings: ${EMBED_CNT}  |  Communities: ${COMM_CNT}  |  PredictedLinks: ${PRED_CNT}  "

    if [ "${INSIGHT_CNT:-0}" -ge 50 ] && \
       [ "${EMBED_CNT:-0}" -gt 0 ] && \
       [ "${COMM_CNT:-0}" -gt 0 ] && \
       [ "${PRED_CNT:-0}" -gt 0 ]; then
        echo ""
        info "All enrichments ready!"
        break
    fi

    echo ""
    sleep "$step"
    elapsed=$((elapsed + step))
done

if [ "$elapsed" -ge "$max_wait" ]; then
    warning "Enrichments not fully ready after 5 minutes. Demo may still work with partial data."
    warning "Insights: ${INSIGHT_CNT}  Embeddings: ${EMBED_CNT}  Communities: ${COMM_CNT}  PredictedLinks: ${PRED_CNT}"
fi

# ---------------------------------------------------------------------------
# 6. Print "Ready to demo" message
# ---------------------------------------------------------------------------
echo ""
echo -e "${GREEN}=========================================================${NC}"
echo -e "${GREEN}  Ready to demo. Now in Claude Desktop ask:${NC}"
echo -e "${GREEN}=========================================================${NC}"
echo ""
echo -e "${YELLOW}Q1 — Matching properties + brokers from an insight:${NC}"
echo '  "Based on the latest Dallas Industrial absorption insight,'
echo '   what are the matching properties and brokers I can reach out to?"'
echo ""
echo -e "${YELLOW}Q2 — Next best actions on a deal:${NC}"
echo '  "Based on my deal PUR-001 in its current state, what actions can I take?"'
echo ""
echo -e "${YELLOW}Q3 — Best broker recommendation:${NC}"
echo '  "Who is the best broker to work with me on an Industrial deal'
echo '   in Dallas for tenant representation?"'
echo ""
echo -e "${GREEN}=========================================================${NC}"
echo -e "  Neo4j Browser: ${YELLOW}http://localhost:7474${NC} (user: neo4j)"
echo -e "  Ingester log:  /tmp/cre_ingester.log"
echo -e "  ML log:        /tmp/cre_ml.log"
echo -e "${GREEN}=========================================================${NC}"
