"""Commands that create or change objects, with the safety rules built in.

- Everything is created PAUSED.
- --dry-run sends the request with execution_options=validate_only: Meta checks it and creates nothing.
- Turning ads on and deleting need --confirm. Without it no request is sent.
- A budget change over 20% needs --force, and the new budget is read back after the write.

Each command takes a GraphClient and the parsed arguments.
"""
import sys


def cents(usd_amount):
    return int(round(float(usd_amount) * 100))


def usd(minor):
    return f"${int(minor) / 100:.2f}" if minor not in (None, "") else ""


def dry(a, params):
    if getattr(a, "dry_run", False):
        params["execution_options"] = ["validate_only"]
    return params


def done(a, res, label):
    if getattr(a, "dry_run", False):
        print(f"✅ check passed, {label} NOT created (--dry-run)")
        return None
    print(f"✅ {label}: {res['id']} (paused)")
    return res["id"]


def cmd_create_campaign(api, a):
    params = {"name": a.name, "objective": a.objective, "status": "PAUSED",
              "special_ad_categories": a.special.split(",") if a.special else [],
              "is_adset_budget_sharing_enabled": False}
    if a.special:
        if not a.countries:
            sys.exit("--countries is required with --special")
        params["special_ad_category_country"] = a.countries.split(",")
    return done(a, api.call("POST", f"{a.account}/campaigns", dry(a, params)), "campaign")


def cmd_status(api, a):
    if a.status == "ACTIVE" and not a.confirm:
        sys.exit("Turning ads on starts spending money. "
                 "Run again with --confirm only after the account owner says yes.")
    for oid in a.ids:
        api.call("POST", oid, {"status": a.status})
        print(f"✅ {oid} → {a.status}")


def cmd_budget(api, a):
    before = api.call("GET", a.id, {"fields": "name,daily_budget"})
    old, new = int(before.get("daily_budget") or 0), cents(a.usd)
    change = (new - old) / old if old else 0
    print(f"{before.get('name', a.id)}: {usd(old) or 'none'} → {usd(new)} ({change:+.0%})")
    if old and abs(change) > 0.2 and not a.force:
        sys.exit("A change over 20% resets Meta's learning phase. Run again with --force if this is intended.")
    api.call("POST", a.id, {"daily_budget": new})
    after = int(api.call("GET", a.id, {"fields": "daily_budget"}).get("daily_budget") or 0)
    if after != new:
        sys.exit(f"❌ Meta shows {usd(after)} instead of {usd(new)}, check in Ads Manager")
    print(f"✅ applied and verified: {usd(after)}")


def cmd_delete(api, a):
    if not a.confirm:
        sys.exit("Deleting cannot be undone. Run again with --confirm.")
    for oid in a.ids:
        api.call("DELETE", oid)
        print(f"🗑 {oid} deleted")
