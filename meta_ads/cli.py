"""Command line entry point: an AI agent or a script drives the ad account through these commands.

    python -m meta_ads -h                 list of commands
    python -m meta_ads <command> -h       options of one command

This repository holds a subset of the commands: the ones that create or change objects
and carry the safety rules.
"""
import argparse
import sys
import urllib.request

from .commands import cmd_budget, cmd_create_campaign, cmd_delete, cmd_status
from .config import load_env
from .graph import GraphClient, MetaError


def build_parser():
    p = argparse.ArgumentParser(prog="meta_ads", description="Meta Ads toolkit")
    p.add_argument("--env", default=".env", help="file with META_ACCESS_TOKEN and META_AD_ACCOUNT_ID")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("create-campaign", help="campaign (paused)")
    s.add_argument("--name", required=True)
    s.add_argument("--objective", default="OUTCOME_TRAFFIC",
                   choices=["OUTCOME_TRAFFIC", "OUTCOME_LEADS", "OUTCOME_ENGAGEMENT", "OUTCOME_AWARENESS",
                            "OUTCOME_SALES"],
                   help="website lead form: OUTCOME_LEADS; Instagram Direct: OUTCOME_ENGAGEMENT")
    s.add_argument("--special", help="special ad category when Meta requires one, e.g. HOUSING")
    s.add_argument("--countries", help="countries for the special ad category, comma separated")
    s.add_argument("--dry-run", action="store_true", help="Meta validates the request, nothing is created")
    s.set_defaults(fn=cmd_create_campaign)

    s = sub.add_parser("status", help="turn on / pause")
    s.add_argument("status", choices=["ACTIVE", "PAUSED"])
    s.add_argument("ids", nargs="+")
    s.add_argument("--confirm", action="store_true", help="required for ACTIVE: ads start spending money")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("budget", help="change the daily budget of an ad set or campaign (shows before and after)")
    s.add_argument("id")
    s.add_argument("usd")
    s.add_argument("--force", action="store_true", help="allow a change over 20%%")
    s.set_defaults(fn=cmd_budget)

    s = sub.add_parser("delete", help="delete objects")
    s.add_argument("ids", nargs="+")
    s.add_argument("--confirm", action="store_true")
    s.set_defaults(fn=cmd_delete)
    return p


def main(argv=None, opener=urllib.request.urlopen):
    a = build_parser().parse_args(argv)
    env = load_env(a.env)
    a.account = env["META_AD_ACCOUNT_ID"]
    api = GraphClient(env["META_ACCESS_TOKEN"], opener=opener)
    try:
        return a.fn(api, a)
    except MetaError as e:
        sys.exit(f"❌ Meta: {e}")


if __name__ == "__main__":
    main()
