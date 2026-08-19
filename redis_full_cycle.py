import json
import os
import re
import time

import requests
from playwright.sync_api import sync_playwright

MAILTM = "https://api.mail.tm"
REDIS = "https://cloud.redis.io"
DATA_DIR = os.environ.get("PX_PROFILE_DIR", os.path.expanduser("~/.redis-px-profile"))
PX_ARCHIVE = os.environ.get("PX_PROFILE_ARCHIVE", "")


def extract_profile():
    if PX_ARCHIVE and os.path.isfile(PX_ARCHIVE) and not os.path.isdir(DATA_DIR):
        import subprocess
        subprocess.run(["bash", "-c", f"mkdir -p '{DATA_DIR}' && tar -xzf '{PX_ARCHIVE}' -C '{DATA_DIR}' --strip-components=1"], check=True)
        print("PX profile restored from archive to", DATA_DIR)


def create_mailbox():
    s = requests.Session()
    domain = s.get(f"{MAILTM}/domains").json()["hydra:member"][0]["domain"]
    address = "redisuser%d@%s" % (int(time.time()) % 10000, domain)
    password = "MailTm#%d!" % (int(time.time()) % 10000)
    r = s.post(f"{MAILTM}/accounts", json={"address": address, "password": password})
    r.raise_for_status()
    return address, password


JS_REGISTER = """(async (user) => {
    const csrfRes = await fetch(location.origin + '/api/v1/csrf', {credentials:'include'});
    let token = null;
    let csrfBody = '';
    try { token = (await csrfRes.json()).csrfToken.csrf_token; } catch(e) {
        try { csrfBody = await csrfRes.text(); } catch(ex) {}
        return {error: 'csrf failed', status: csrfRes.status, body: csrfBody.slice(0, 400)};
    }
    const r = await fetch(location.origin + '/api/v1/users', {
        method: 'POST',
        credentials: 'include',
        headers: {'Content-Type': 'application/json', 'X-CSRF-Token': token},
        body: JSON.stringify({user: user})
    });
    return {status: r.status, body: await r.text()};
})"""


def register_redis_user(email, password):
    user = {
        "email": email,
        "password": password,
        "password_confirmation": password,
        "first_name": "Ahmed",
        "last_name": "Karim",
        "company": "TechLabs",
        "country": "EG",
        "title": None,
        "email_alerts": True,
        "operational_emails": True,
        "billing": True,
        "permission": "owner",
        "role": "owner",
    }
    last = None
    for attempt in range(3):
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(
                DATA_DIR, headless=True,
                args=["--disable-blink-features=AutomationControlled"])
            page = ctx.new_page()
            page.goto(REDIS, wait_until="networkidle", timeout=90000)
            page.wait_for_timeout(8000)
            res = page.evaluate(JS_REGISTER, user)
            ctx.close()
        last = res
        if res.get("status") in (200, 201):
            return res
        print("Register attempt %d failed (%s), retrying..." % (attempt + 1, res.get("status")))
        time.sleep(5)
    return last


def poll_activation(email, password, max_wait=240):
    s = requests.Session()
    deadline = time.time() + max_wait
    while time.time() < deadline:
        r = s.post(f"{MAILTM}/token",
                   json={"address": email, "password": password})
        if not r.ok:
            time.sleep(10)
            continue
        token = r.json()["token"]
        h = {"Authorization": f"Bearer {token}"}
        msgs = s.get(f"{MAILTM}/messages", headers=h).json().get("hydra:member", [])
        candidates = [m for m in msgs
                      if "redis" in m["subject"].lower()
                      or "redis" in m.get("from", {}).get("address", "").lower()]
        if not candidates:
            print("Waiting for Redis activation email...")
            time.sleep(10)
            continue
        body = s.get(f"{MAILTM}/messages/{candidates[0]['id']}", headers=h).json()
        html = body.get("html") or body.get("text", "")
        if isinstance(html, list):
            html = "\n".join(html)
        links = [l for l in re.findall(r"https://[A-Za-z0-9./\-_%&=?:;,#]+", html)
                 if "activate" in l.lower() or "cloud.redis" in l]
        if links:
            print("Activation email received.")
            return links[0]
        time.sleep(10)
    raise RuntimeError("No activation email arrived in time")


JS_ACTIVATE_AND_URL = """(async (link) => {
    const nav = await fetch(link, {credentials: 'include'});
    if (!nav.ok) return {error: 'activation fetch failed', status: nav.status};

    const url = new URL(link);
    const email = url.searchParams.get('u');

    const me = await fetch(location.origin + '/api/v1/users?limit=50', {credentials:'include'});

    const csrfRes = await fetch(location.origin + '/api/v1/csrf', {credentials:'include'});
    const t = (await csrfRes.json()).csrfToken.csrf_token;
    const hdr = {credentials:'include', headers:{'X-CSRF-Token': t}};

    let loginStatus = null;
    if (me.ok) {
        const users = (await me.json()).users || [];
        loginStatus = users.length ? 200 : null;
    }

    const subRes = await fetch(location.origin + '/api/v1/subscriptions?limit=50', hdr);
    const subs = (await subRes.json()).subscriptions || [];
    const sub = subs.find(s => String(s.plan) === 'free') || subs[0];
    if (!sub) return {error: 'no subscription', loginStatus, nav: nav.status};

    let bdbId = null;
    for (const u of [
        location.origin + '/api/v1/subscriptions/' + sub.id + '/bdbs?limit=10',
        location.origin + '/api/v1/bdbs?limit=50'
    ]) {
        const r = await fetch(u, hdr);
        if (r.ok) {
            const d = await r.json();
            const list = d.bdbs || d.data || [];
            if (list.length) { bdbId = list[0].id; break; }
        }
    }
    if (!bdbId) return {error: 'no database', loginStatus, nav: nav.status};

    let bdbInfo = null;
    for (let i = 0; i < 60; i++) {
        const r = await fetch(location.origin + '/api/v1/bdbs/' + bdbId + '?get_credentials=2&with_credentials=true', hdr);
        if (r.ok) {
            const d = await r.json();
            const b = d.bdb;
            if (b && b.status === 'active' && b.dns_master_public) { bdbInfo = b; break; }
        }
        await new Promise(res => setTimeout(res, 5000));
    }
    if (!bdbInfo) return {error: 'database never became active', loginStatus, nav: nav.status};

    const ac = bdbInfo.access_control || {};
    return {
        ok: true,
        loginStatus: loginStatus || nav.status,
        db: {id: bdbInfo.id, name: bdbInfo.name, version: bdbInfo.redis_version},
        url: 'redis://default:' + ac.redis_password + '@' + bdbInfo.dns_master_public,
        plan: sub.plan, subscription: sub.id
    };
})"""


def activate_and_get_url(activation_link):
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(DATA_DIR, headless=True)
        page = ctx.new_page()
        page.goto(REDIS, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(3000)
        res = page.evaluate(JS_ACTIVATE_AND_URL, activation_link)
        ctx.close()
    return res


def test_url(url):
    import redis as rlib

    client = rlib.from_url(url, decode_responses=True)
    print("PING ->", client.ping())
    client.set("created_by_script", "yes")
    print("SET created_by_script -> OK")
    print("GET created_by_script ->", client.get("created_by_script"))


def main():
    import sys

    extract_profile()

    print("=" * 60)
    print("STEP 1: creating temporary mailbox (mail.tm)...")
    email, mail_pw = create_mailbox()
    print(f"  email:    {email}\n  mailbox password: {mail_pw}")

    print("STEP 2: registering Redis account with fake data...")
    redis_pw = "Redis#%d!" % (int(time.time()) % 10000)
    res = register_redis_user(email, redis_pw)
    print("  register status:", res["status"])
    if res["status"] not in (200, 201):
        print("  response:", json.dumps(res)[:600])
        sys.exit(1)

    print("STEP 3: waiting for activation email...")
    link = poll_activation(email, mail_pw)
    print("  link:", link[:90], "...")

    print("STEP 4: activating account and fetching free database...")
    info = activate_and_get_url(link)
    if not info.get("ok"):
        print("Failed:", json.dumps(info, indent=2))
        sys.exit(1)

    print()
    print("=" * 60)
    print("EMAIL (Redis login):", email)
    print("PASSWORD (Redis):   ", redis_pw)
    print("STORAGE URL:        ", info["url"])
    print("=" * 60)
    print("DB:", info["db"]["name"], "v" + info["db"]["version"])
    print("CLI: redis-cli -u", info["url"])
    print()
    out_file = os.environ.get("RESULT_FILE", "redis_new_account.json")
    json.dump({"email": email, "password": redis_pw,
               "mailbox_password": mail_pw,
               "url": info["url"], "db": info["db"],
               "subscription": info["subscription"]},
              open(out_file, "w"), indent=2)
    print("Saved to", out_file)

    if len(sys.argv) > 1 and sys.argv[1] == "test":
        print()
        test_url(info["url"])


if __name__ == "__main__":
    main()
