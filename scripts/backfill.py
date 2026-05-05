#!/usr/bin/env python3
"""
Convenience entry point: python scripts/backfill.py

Delegates to ingester.backfill.main() so the README quick-start path works
without knowing about Python module syntax.
"""
import sys
import os

# Ensure project root is on sys.path when run directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingester.backfill import main

if __name__ == "__main__":
    main()
