"""Flags shared by every demo script."""

from __future__ import annotations

import argparse
import os

from dm.client import DEFAULT_MODEL


def common_parser(description: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--model", default=DEFAULT_MODEL, help="Ollaya model, e.g. laya:en, kev:0.8b (default: %(default)s)")
    p.add_argument("--replay", action="store_true", help="answer only from fixtures/, never call the server")
    return p


def parse(p: argparse.ArgumentParser) -> argparse.Namespace:
    """Parse args and switch on replay mode before any Decider is built."""
    args = p.parse_args()
    if args.replay:
        os.environ["DM_REPLAY"] = "1"
    return args
