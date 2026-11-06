"""Who is calling, when the caller is not a person.

A browser signs in with Windows and the DMS answers what AD lets that person see. An application has no
Windows sign-in and no AD rights: Priority, a report, a script on another server. It is given a key instead,
and the key is an identity - it has a name, it says what that caller may read, and every call it makes is
written to the log under that name.

    DMS_API_KEYS=priority:9f3c...:customers,documents:svc_priority@rh.co.il | reports:4a81...:customers:...

One line per caller: its name, its key, what it may ask for, and **the AD account it acts as**. That last
part is the point: an application is not a super user. Everything it is told is first checked against that
account's own AD rights, folder by folder, exactly as the DMS checks a person - so a caller sees what its
account may see on the file server and nothing else. A caller with no account named is told nothing at all.

The key is a secret: it is never written to the log, never answered back, and a caller that sends the wrong
one is simply not known.
"""
from __future__ import annotations

import hmac
import logging
import os
import secrets

log = logging.getLogger("dms_api.api")
SCOPES = ("customers", "documents", "files", "kpi")


def parse(value: str) -> dict[str, dict]:
    """DMS_API_KEYS -> {key: {"name": ..., "scopes": [...]}}. A line the DMS cannot read is said so and
    left out: a caller with no scopes could otherwise look like one with every scope."""
    out: dict[str, dict] = {}
    for one in (value or "").replace("\n", "|").split("|"):
        one = one.strip()
        if not one or one.startswith("#"):
            continue
        bits = [b.strip() for b in one.split(":")]
        if len(bits) < 2 or not bits[0] or not bits[1]:
            log.warning("DMS_API_KEYS: a caller was left out, it is not <name>:<key>[:<scopes>]")
            continue
        name, key = bits[0], bits[1]
        scopes = [x.strip().lower() for x in (bits[2] if len(bits) > 2 else "").split(",") if x.strip()]
        bad = [x for x in scopes if x not in SCOPES]
        if bad:
            log.warning("DMS_API_KEYS: %s asks for something that is not a scope: %s", name, ", ".join(bad))
        acts_as = bits[3] if len(bits) > 3 else ""
        if not acts_as:
            log.warning("DMS_API_KEYS: %s names no AD account to act as, so it will be told nothing", name)
        out[key] = {"name": name, "scopes": [x for x in scopes if x in SCOPES] or ["customers"],
                    "as": acts_as}
    return out


def caller(keys: dict[str, dict], sent: str) -> dict | None:
    """The caller that key belongs to, or None. Compared so that a wrong key tells nobody how wrong it was."""
    if not sent or not keys:
        return None
    for key, who in keys.items():
        if hmac.compare_digest(key, sent):
            return who
    return None


def new_key() -> str:
    """A key to put in .env. Nothing of the DMS depends on its shape; it only has to be unguessable."""
    return secrets.token_urlsafe(32)


if __name__ == "__main__":                 # python -m dms_api.apikeys <name> [scopes]
    import sys
    name = sys.argv[1] if len(sys.argv) > 1 else "caller"
    scopes = sys.argv[2] if len(sys.argv) > 2 else "customers"
    acts_as = sys.argv[3] if len(sys.argv) > 3 else ""
    print(f"{name}:{new_key()}:{scopes}:{acts_as}")
    if not acts_as:
        print("\nNo AD account was given, so this caller would be told nothing: add the account it acts as\n"
              "at the end of the line (svc_something@rh.co.il).", file=sys.stderr)
    print("\nAdd it to webapi\\.env, after DMS_API_KEYS= (several callers are separated by |),", file=sys.stderr)
    print("then .\\scripts\\Restart-Dms.ps1. Keep the key: the DMS never shows it again.", file=sys.stderr)
