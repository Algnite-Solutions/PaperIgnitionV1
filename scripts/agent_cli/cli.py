#!/usr/bin/env python3
"""PaperIgnition Agent CLI — search papers and read digests via API key."""

import argparse
import json
import os
import sys

import httpx

from .client import PaperIgnitionClient


def main():
    parser = argparse.ArgumentParser(description="PaperIgnition Agent CLI")
    parser.add_argument("--base-url", default=os.environ.get("PI_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--api-key", default=os.environ.get("PI_API_KEY"))
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")

    sub = parser.add_subparsers(dest="command")

    # search (semantic)
    sv = sub.add_parser("search", help="Semantic vector search")
    sv.add_argument("query")
    sv.add_argument("--top-k", type=int, default=10)
    sv.add_argument("--cutoff", type=float, default=0.1)

    # search-bm25
    sb = sub.add_parser("search-bm25", help="BM25 full-text search")
    sb.add_argument("query")
    sb.add_argument("--top-k", type=int, default=10)

    # metadata
    md = sub.add_parser("metadata", help="Get paper metadata")
    md.add_argument("doc_id")

    # content
    ct = sub.add_parser("content", help="Get paper blog content")
    ct.add_argument("paper_id")

    # digest list
    dl = sub.add_parser("digest-list", help="List daily digest recommendations")
    dl.add_argument("username")
    dl.add_argument("--limit", type=int, default=50)

    # digest blog
    db = sub.add_parser("digest-blog", help="Read personalized blog for a paper")
    db.add_argument("paper_id")
    db.add_argument("username")

    args = parser.parse_args()

    if not args.api_key:
        print("Error: --api-key or PI_API_KEY env var required", file=sys.stderr)
        sys.exit(2)

    if not args.command:
        parser.print_help()
        sys.exit(1)

    client = PaperIgnitionClient(args.base_url, args.api_key)

    try:
        if args.command == "search":
            result = client.find_similar(args.query, args.top_k, args.cutoff)
        elif args.command == "search-bm25":
            result = client.find_similar_bm25(args.query, args.top_k)
        elif args.command == "metadata":
            result = client.get_paper_metadata(args.doc_id)
        elif args.command == "content":
            result = client.get_paper_content(args.paper_id)
        elif args.command == "digest-list":
            result = client.get_recommendations(args.username, args.limit)
        elif args.command == "digest-blog":
            result = client.get_blog_content(args.paper_id, args.username)
        else:
            parser.print_help()
            sys.exit(1)

        if isinstance(result, str):
            print(result)
        else:
            indent = 2 if args.pretty else None
            print(json.dumps(result, indent=indent, ensure_ascii=False))
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            print("Error: Unauthorized — check your API key", file=sys.stderr)
            sys.exit(3)
        elif e.response.status_code == 429:
            retry = e.response.headers.get("Retry-After", "unknown")
            print(f"Error: Rate limited. Retry after {retry}s", file=sys.stderr)
            sys.exit(4)
        elif e.response.status_code >= 500:
            print(f"Error: Server error ({e.response.status_code})", file=sys.stderr)
            sys.exit(5)
        else:
            print(f"Error: {e.response.status_code} — {e.response.text}", file=sys.stderr)
            sys.exit(1)
    except httpx.ConnectError:
        print(f"Error: Cannot connect to {args.base_url}", file=sys.stderr)
        sys.exit(1)
