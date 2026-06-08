#!/usr/bin/env python3
"""Daily collection runner — fetches all data sources and summarises with Claude.

Run: python scripts/collect_all.py [--no-summarise] [--sources crime,planning,...]
"""
import argparse
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent))

from collectors import (
    CrimeCollector, PlanningCollector, CourtsCollector, CouncilCollector,
    EnvironmentCollector, PropertyCollector, TrainsCollector, BinsCollector,
    EventsCollector, SportsCollector, RoadsCollector,
)
from summariser import Summariser

def trigger_redeploy():
    print("GitHub Pages will redeploy automatically on push")


ALL_COLLECTORS = {
    "crime": CrimeCollector,
    "planning": PlanningCollector,
    "courts": CourtsCollector,
    "council": CouncilCollector,
    "environment": EnvironmentCollector,
    "property": PropertyCollector,
    "trains": TrainsCollector,
    "bins": BinsCollector,
    "events": EventsCollector,
    "sports": SportsCollector,
    "roads": RoadsCollector,
}


def main():
    parser = argparse.ArgumentParser(description="Collect all Bugle data sources")
    parser.add_argument("--no-summarise", action="store_true",
                        help="Skip Claude summarisation step")
    parser.add_argument("--sources", default="",
                        help="Comma-separated list of sources to run (default: all)")
    parser.add_argument("--output-dir", default="public/data/output",
                        help="Output directory for JSON files")
    args = parser.parse_args()

    sources = (
        {k: v for k, v in ALL_COLLECTORS.items() if k in args.sources.split(",")}
        if args.sources
        else ALL_COLLECTORS
    )

    print(f"Running {len(sources)} collector(s)...")
    results = []
    for name, cls in sources.items():
        print(f"\n→ {name}")
        try:
            result = cls().run(output_dir=args.output_dir)
            results.append(result)
        except Exception as exc:
            print(f"  ERROR: {exc}")

    if not args.no_summarise and results:
        print(f"\nSummarising {sum(len(r.items) for r in results)} items with Claude...")
        summariser = Summariser()
        for result in results:
            if result.items:
                try:
                    enriched = summariser.enrich(result)
                    enriched.save(args.output_dir)
                    print(f"  ✓ {result.source}")
                except Exception as exc:
                    print(f"  ✗ {result.source}: {exc}")

    total = sum(len(r.items) for r in results)
    print(f"\nDone. {total} items collected across {len(results)} sources.")


if __name__ == "__main__":
    main()
