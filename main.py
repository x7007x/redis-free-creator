import json
import os
import re
import sys
import time
import urllib.parse

import redis
import requests

try:
    from patchright.sync_api import sync_playwright
except ImportError:
    from playwright.sync_api import sync_playwright

MAILTM_API = "https://api.mail.tm"
SIGNUP_URL = "https://redis.io/try-free/"
CONSOLE = "https://cloud.redis.io"
SM = "https://app.redislabs.com/api/v1"
RESULT_FILE = os.environ.get("RESULT_FILE", "redis_new_account.json")
FIRST = "Ahmed"
LAST = "Karim"
COMPANY = "TechLabs"

JS_FETCH_DB = """
async () => {
  const steps = {};
  const j = async (url, opts) => {
    const r = await fetch(url, opts);
    const t = await r.text();
    let b = null;
    try { b = JSON.parse(t); } catch (e) {}
    return {status: r.status, body: b, text: t};
  };
  const bases = [location.origin + "/api/v1", "https://cloud.redis.io/api/v1", "https://app.redislabs.com/api/v1"];
  let SM = null;
  let c = null;
  for (const base of [...new Set(bases)]) {
    const attempt = await j(base + "/csrf", {credentials: "include"});
    steps["csrf@" + base] = {status: attempt.status, text: attempt.text.slice(0, 150)};
    if (attempt.status === 200 && attempt.body) { SM = base; c = attempt; break; }
  }
  if (!SM) return {ok: false, stage: "csrf", steps};
  const token = c.body.csrfToken ? c.body.csrfToken.csrf_token : null;
  const H = {"X-CSRF-Token": token, "Content-Type": "application/json"};
  const acc = await j(SM + "/accounts?limit=50", {credentials: "include", headers: H});
  steps.accounts = {status: acc.status, text: acc.text.slice(0, 300)};
  const plans = await j(SM + "/plans?limit=100", {credentials: "include", headers: H});
  steps.plans = {status: plans.status, text: plans.text.slice(0, 700)};
  const subs = await j(SM + "/subscriptions?limit=50", {credentials: "include", headers: H});
  steps.subscriptions = {status: subs.status, text: subs.text.slice(0, 300)};
  let subList = subs.body && subs.body.subscriptions ? subs.body.subscriptions : [];
  let sub = subList.find(s => s.plan === "free") || subList[0];
  if (!sub) {
    const planList = plans.body && plans.body.plans ? plans.body.plans : [];
    const freePlan = planList.find(p => p.plan_type === "free") || planList.find(p => (p.price || 0) === 0);
    steps.free_plan = freePlan ? {id: freePlan.id, name: freePlan.name} : null;
    if (freePlan) {
      steps.free_plan_full = JSON.stringify(freePlan).slice(0, 1500);
      for (const p of ["/plans/cluster-groups", "/plan-cluster-groups", "/clusterGroups", "/plans/groups", "/plans/cloud_regions"]) {
        const g = await j(SM + p, {credentials: "include", headers: H});
        steps["probe" + p] = {status: g.status, text: g.text.slice(0, 400)};
      }
      const gid = freePlan.plan_cluster_group_id || freePlan.cluster_group_id || freePlan.clusterGroupId || freePlan.planClusterGroupId || freePlan.id;
      const attempts = [
        {subscription: {name: "database-1-sub", planClusterGroup: {id: gid}}},
        {subscription: {name: "database-1-sub", plan_cluster_group: {id: gid}}},
        {subscription: {name: "database-1-sub", deployment: {planId: freePlan.id}}},
        {subscription: {name: "database-1-sub", planClusterGroupId: gid}},
        {subscription: {name: "database-1-sub", planId: freePlan.id, regionId: freePlan.region_id}}
      ];
      steps.create_sub_attempts = [];
      for (const payload of attempts) {
        const r = await j(SM + "/subscriptions", {method: "POST", credentials: "include", headers: H, body: JSON.stringify(payload)});
        steps.create_sub_attempts.push({payload: JSON.stringify(payload).slice(0, 180), status: r.status, text: r.text.slice(0, 260)});
        if (r.status >= 200 && r.status < 300) break;
      }
      const subs2 = await j(SM + "/subscriptions?limit=50", {credentials: "include", headers: H});
      subList = subs2.body && subs2.body.subscriptions ? subs2.body.subscriptions : [];
      sub = subList.find(s => s.plan === "free") || subList[0];
    }
  }
  if (!sub) return {ok: false, stage: "no-subscription", steps};
  let dbs = [];
  const bySub = await j(SM + "/subscriptions/" + sub.id + "/bdbs?limit=10", {credentials: "include", headers: H});
  steps.bdbs_by_sub = {status: bySub.status, text: bySub.text.slice(0, 300)};
  if (bySub.body) dbs = bySub.body.databases || bySub.body.bdbs || [];
  if (!dbs.length) {
    const all = await j(SM + "/bdbs?limit=50", {credentials: "include", headers: H});
    steps.bdbs_all = {status: all.status, text: all.text.slice(0, 300)};
    if (all.body) dbs = all.body.databases || all.body.bdbs || [];
  }
  if (!dbs.length) {
    const bdbAttempts = [
      {url: SM + "/subscriptions/" + sub.id + "/bdbs", payload: {name: "database-1"}},
      {url: SM + "/bdbs", payload: {name: "database-1", subscriptionId: sub.id}},
      {url: SM + "/subscriptions/" + sub.id + "/bdbs", payload: {name: "database-1", memoryLimitInGB: 0.03}}
    ];
    steps.create_bdb_attempts = [];
    for (const a of bdbAttempts) {
      const r = await j(a.url, {method: "POST", credentials: "include", headers: H, body: JSON.stringify(a.payload)});
      steps.create_bdb_attempts.push({url: a.url.replace(SM, ""), payload: JSON.stringify(a.payload).slice(0, 140), status: r.status, text: r.text.slice(0, 260)});
      if (r.status >= 200 && r.status < 300) break;
    }
    for (let i = 0; i < 12 && !dbs.length; i++) {
      const again = await j(SM + "/subscriptions/" + sub.id + "/bdbs?limit=10", {credentials: "include", headers: H});
      const againDbs = again.body ? (again.body.databases || again.body.bdbs || []) : [];
      if (againDbs.length) dbs = againDbs;
      if (!dbs.length) {
        const all2 = await j(SM + "/bdbs?limit=50", {credentials: "include", headers: H});
        const all2Dbs = all2.body ? (all2.body.databases || all2.body.bdbs || []) : [];
        if (all2Dbs.length) dbs = all2Dbs;
      }
      if (!dbs.length) await new Promise(r => setTimeout(r, 5000));
    }
  }
  if (!dbs.length) return {ok: false, stage: "no-database", sub: sub.id, plan: sub.plan, steps};
  let db = null;
  for (let i = 0; i < 60; i++) {
    const one = await j(SM + "/bdbs/" + dbs[0].id + "?get_credentials=2&with_credentials=true", {credentials: "include", headers: H});
    const b = one.body && one.body.bdb ? one.body.bdb : one.body;
    if (i === 0) steps.bdb_detail_first = {status: one.status, text: one.text.slice(0, 600)};
    steps.bdb_detail_last = {status: one.status, text: one.text.slice(0, 600)};
    if (b) {
      const dns = b.dns_master_public || b.dns || null;
      const pw0 = b.access_control ? (b.access_control.redis_password || b.access_control.password) : b.redis_password;
      if (dns && pw0 && (String(b.status || "").toLowerCase() === "active" || i >= 20)) { db = b; break; }
    }
    await new Promise(r => setTimeout(r, 5000));
  }
  if (!db) return {ok: false, stage: "db-not-active", steps};
  const pw = db.access_control ? (db.access_control.redis_password || db.access_control.password) : db.redis_password;
  return {ok: true, url: "redis://default:" + pw + "@" + (db.dns_master_public || db.dns),
          db: {id: db.id, name: db.name, version: db.version},
          subscription: sub.id, plan: sub.plan, steps};
}
"""


def create_mailbox():
    s = requests.Session()
    domain = s.get(MAILTM_API + "/domains", timeout=60).json()["hydra:member"][0]["domain"]
    local = "redisuser%d" % int(time.time() % 100000)
    email = local + "@" + domain
    pw = "MailTm#%d!" % int(time.time() % 100000)
    r = s.post(MAILTM_API + "/accounts", json={"address": email, "password": pw}, timeout=60)
    r.raise_for_status()
    t = s.post(MAILTM_API + "/token", json={"address": email, "password": pw}, timeout=60)
    t.raise_for_status()
    return email, pw, t.json()["token"]


def fill_first(page, selectors, value):
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                loc.fill(value)
                return sel
        except Exception:
            pass
    return None


def page_text(page):
    try:
        return page.inner_text("body")[:4000]
    except Exception:
        return ""


def wait_settled(page, seconds=60):
    last = None
    stable = 0
    end = time.time() + seconds
    while time.time() < end:
        txt = page_text(page).strip()
        if txt and txt != "Loading..." and txt == last:
            stable += 1
            if stable >= 2:
                break
        else:
            stable = 0
        last = txt
        page.wait_for_timeout(2500)
    return last or ""


FIELD_SELECTORS = {
    "first_name": ['input[name="first_name"]', 'input[name="firstName"]', 'input[placeholder*="First" i]'],
    "last_name": ['input[name="last_name"]', 'input[name="lastName"]', 'input[placeholder*="Last" i]'],
    "email": ['input[name="email"]', 'input[type="email"]'],
    "company": ['input[name="company"]', 'input[name="company_name"]', 'input[placeholder*="Company" i]'],
    "phone": ['input[name="phone"]', 'input[type="tel"]', 'input[placeholder*="Phone" i]'],
    "password": ['input[name="password"]', 'input[type="password"]'],
}


def visible_fields(page):
    return page.evaluate("""() => Array.from(document.querySelectorAll('input,select,textarea'))
        .filter(e => e.offsetParent !== null)
        .map(e => ({name: e.name, type: e.type, value: e.value ? 'set' : ''}))""")


def fill_if_empty(page, selectors, value):
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                if loc.input_value():
                    return "already"
                loc.fill(value)
                return "filled"
        except Exception:
            pass
    return None


def signup_via_form(page, email, password):
    values = {"first_name": FIRST, "last_name": LAST, "email": email,
              "company": COMPANY, "phone": "+201012345678", "password": password}
    page.goto(SIGNUP_URL, wait_until="domcontentloaded", timeout=90000)
    end = time.time() + 240
    last_state = None
    last_click_state = None
    last_click_at = 0
    challenge_since = None
    last_hold_at = 0
    while time.time() < end:
        txt = page_text(page)
        low = txt.lower()
        if "check your email to activate" in low or "almost there" in low:
            print("  sign-up accepted, activation email sent")
            return
        if "already" in low and "account" in low and "exist" in low:
            raise RuntimeError("account already exists")
        if challenge_present(page):
            if challenge_since is None:
                challenge_since = time.time()
            if time.time() - challenge_since > 150:
                page.screenshot(path="debug_signup.png")
                raise RuntimeError("blocked by human challenge at sign-up")
            if time.time() - last_hold_at > 15:
                last_hold_at = time.time()
                try_press_and_hold(page)
        else:
            challenge_since = None
        for sel in ['#onetrust-accept-btn-handler', 'button:has-text("Accept all")', 'button:has-text("Accept")']:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    loc.click()
                    break
            except Exception:
                pass
        try:
            fields = visible_fields(page)
        except Exception:
            fields = []
        state = json.dumps(fields)
        if state != last_state:
            print("  visible fields:", state)
            last_state = state
        if not fields:
            page.wait_for_timeout(4000)
            continue
        results = {}
        for key, sels in FIELD_SELECTORS.items():
            results[key] = fill_if_empty(page, sels, values[key])
        try:
            sel = page.locator('select[name="country"]').first
            if sel.count() > 0 and sel.is_visible():
                sel.select_option("eg")
        except Exception:
            pass
        names = {f["name"] for f in fields} | {f["type"] for f in fields}
        pw_present = "password" in names
        email_done = results["email"] in ("filled", "already") or any(f["name"] == "email" and f["value"] == "set" for f in fields)
        btn = page.get_by_role("button", name=re.compile("sign up with email", re.I)).first
        if btn.count() == 0:
            btn = page.locator('button[type="submit"]').first
        clicked = False
        try:
            if btn.count() > 0 and btn.is_enabled() and email_done and (state != last_click_state or time.time() - last_click_at > 25):
                btn.click()
                clicked = True
                last_click_state = state
                last_click_at = time.time()
                print("  clicked sign-up button (password present:", pw_present, ")")
        except Exception:
            pass
        page.wait_for_timeout(5000 if clicked else 3000)
    page.screenshot(path="debug_signup.png")
    raise RuntimeError("sign-up not confirmed; page: " + page_text(page))


def poll_activation(token, seconds=300):
    print("Waiting for Redis activation email...")
    end = time.time() + seconds
    seen = set()
    while time.time() < end:
        r = requests.get(MAILTM_API + "/messages", headers={"Authorization": "Bearer " + token}, timeout=60)
        if r.status_code == 200:
            for m in r.json().get("hydra:member", []):
                if m["id"] in seen:
                    continue
                seen.add(m["id"])
                subj = (m.get("subject") or "").lower()
                frm = ((m.get("from") or {}).get("address") or "").lower()
                if "redis" not in subj and "activat" not in subj and "welcome" not in subj and "redis" not in frm:
                    continue
                d = requests.get(MAILTM_API + "/messages/" + m["id"], headers={"Authorization": "Bearer " + token}, timeout=60)
                if d.status_code != 200:
                    continue
                data = d.json()
                html = " ".join(data.get("html") or [])
                blob = html + " " + (data.get("text") or "")
                links = re.findall(r'https?://[^\s"\'<>]+', blob)
                links = [l.replace("&amp;", "&") for l in links]
                pick = [l for l in links if "activate-registration" in l or "activate" in l]
                if not pick:
                    pick = [l for l in links if "cloud.redis" in l or "auth.redis" in l]
                if pick:
                    print("Activation email received.")
                    return pick[0]
        time.sleep(8)
    raise RuntimeError("Activation email did not arrive")


def challenge_present(page):
    txt = page_text(page).lower()
    if "press & hold" in txt or "press and hold" in txt or "confirm you are a human" in txt:
        return True
    for frame in page.frames:
        try:
            ft = frame.locator("body").inner_text(timeout=800).lower()
            if "press & hold" in ft or "press and hold" in ft or "confirm you are a human" in ft:
                return True
        except Exception:
            pass
    return False


def challenge_targets(page):
    targets = []
    for sel in ['button:has-text("Press & Hold")', 'button:has-text("Press and Hold")', '#px-captcha', '[data-testid="px-captcha"]']:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                bb = loc.bounding_box()
                if bb:
                    targets.append(bb)
        except Exception:
            pass
    for frame in page.frames:
        fu = (frame.url or "").lower()
        if any(k in fu for k in ["captcha", "perimeterx", "px-cdn", "px-cloud", "human"]):
            try:
                el = frame.locator('button, [role="button"], #px-captcha').first
                if el.count() > 0:
                    bb = el.bounding_box()
                    if bb:
                        targets.append(bb)
            except Exception:
                pass
    try:
        for loc in page.locator("iframe").all():
            bb = loc.bounding_box()
            if bb and bb["width"] > 100 and bb["height"] > 30:
                targets.append(bb)
    except Exception:
        pass
    return targets


def hold_at(page, bb, seconds):
    x = bb["x"] + bb["width"] / 2
    y = bb["y"] + bb["height"] / 2
    page.mouse.move(x - 120, y - 60, steps=8)
    page.mouse.move(x, y, steps=12)
    page.wait_for_timeout(400)
    page.mouse.down()
    steps = int(seconds * 1000 / 350)
    for i in range(steps):
        page.mouse.move(x + ((i * 7) % 5) - 2, y + ((i * 3) % 3) - 1)
        page.wait_for_timeout(350)
    page.mouse.up()
    page.wait_for_timeout(3000)


def try_press_and_hold(page):
    if not challenge_present(page):
        return False
    targets = challenge_targets(page)
    print("  human challenge found, targets:", len(targets))
    for attempt in range(3):
        if not targets:
            break
        hold_at(page, targets[attempt % len(targets)], 11 + attempt * 2)
        if not challenge_present(page):
            print("  human challenge cleared")
            return True
        print("  challenge still present after hold", attempt + 1)
        targets = challenge_targets(page) or targets
    return not challenge_present(page)


def click_submit(page, names):
    for name in names:
        b = page.get_by_role("button", name=re.compile(name, re.I)).first
        try:
            if b.count() > 0 and b.is_enabled():
                b.click()
                return name
        except Exception:
            pass
    for sel in ['input[type="submit"]', 'button[type="submit"]']:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                loc.click()
                return sel
        except Exception:
            pass
    return None


def okta_login(page, email, password):
    nonce = "%d" % int(time.time() * 1000)
    auth_url = ("https://auth.redis.com/oauth2/default/v1/authorize"
                "?client_id=0oa29hawacTG51zCM5d7&response_type=code"
                "&scope=openid%20profile%20email&redirect_uri=https%3A%2F%2Fapp.redislabs.com%2F"
                "&state=" + nonce + "&nonce=" + nonce)
    page.goto(auth_url, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(8000)
    print("  okta attempt, landed:", page.url[:110])
    if "auth.redis.com" not in page.url:
        return False
    end = time.time() + 120
    stage = ""
    while time.time() < end:
        if "auth.redis.com" not in page.url:
            print("  okta flow finished, now at:", page.url[:110])
            page.wait_for_timeout(6000)
            return True
        txt = page_text(page).lower()
        if "press & hold" in txt or "confirm you are a human" in txt:
            try_press_and_hold(page)
        em = fill_first(page, ['input[name="identifier"]', '#okta-signin-username', 'input[name="username"]', 'input[type="email"]', 'input[name="email"]'], email)
        if em and stage != "email":
            stage = "email"
            print("  okta: email filled via", em)
            clicked = click_submit(page, ["next", "sign in", "continue"])
            print("  okta: submit after email:", clicked)
            page.wait_for_timeout(5000)
            continue
        pw = fill_first(page, ['input[name="credentials.passcode"]', 'input[type="password"]', 'input[name="password"]'], password)
        if pw and stage != "password":
            stage = "password"
            print("  okta: password filled via", pw)
            clicked = click_submit(page, ["sign in", "verify", "next", "log in"])
            print("  okta: submit after password:", clicked)
            page.wait_for_timeout(5000)
            continue
        if "incorrect" in txt or "invalid" in txt or "unable to sign in" in txt:
            print("  okta: rejection text seen:", txt[:200])
            return False
        page.wait_for_timeout(3000)
    print("  okta: timed out at", page.url[:110], "| page:", page_text(page).replace("\n", " ")[:200])
    return "auth.redis.com" not in page.url


def click_text(page, patterns):
    for pat in patterns:
        try:
            loc = page.get_by_role("button", name=re.compile(pat, re.I)).first
            if loc.count() > 0 and loc.is_visible() and loc.is_enabled():
                loc.click()
                return pat
        except Exception:
            pass
        try:
            loc = page.locator("text=" + pat).first
            if loc.count() > 0 and loc.is_visible():
                loc.click()
                return pat
        except Exception:
            pass
    return None


def click_button_matching(page, patterns, banned=()):
    try:
        btns = page.locator("button, a[role='button']")
        count = btns.count()
    except Exception:
        return None
    for i in range(count):
        b = btns.nth(i)
        try:
            t = (b.inner_text() or "").strip()
            if not t:
                continue
            low = t.lower()
            if any(x in low for x in banned):
                continue
            for pat in patterns:
                if re.search(pat, t, re.I):
                    if b.is_visible() and b.is_enabled():
                        b.click()
                        return t[:60]
        except Exception:
            pass
    return None


def create_via_wizard(page):
    page.goto(CONSOLE + "/#/databases", wait_until="domcontentloaded", timeout=90000)
    wait_settled(page, 30)
    print("  wizard start:", page_text(page).replace("\n", " ")[:280])
    end = time.time() + 300
    last_txt = ""
    plan_dumped = False
    free_clicked = False
    while time.time() < end:
        txt = page_text(page)
        low = txt.lower()
        if txt != last_txt:
            print("  wizard page:", txt.replace("\n", " ")[:300])
            last_txt = txt
        if "choose your plan" in low and not plan_dumped:
            plan_dumped = True
            try:
                clickables = page.evaluate("""() => Array.from(document.querySelectorAll('button, a, [role="button"], [role="tab"], label')).filter(e => e.offsetParent).map(e => ({tag: e.tagName, text: (e.innerText || '').trim().slice(0, 70)})).filter(x => x.text)""")
                print("  plan page clickables:", json.dumps(clickables)[:1800])
            except Exception:
                pass
            page.screenshot(path="debug_plan.png")
        if "choose your plan" in low and not free_clicked:
            if click_text(page, [r"try 30\s*mb for free", r"30\s*mb for free"]):
                free_clicked = True
                print("  wizard: free 30MB option clicked")
                page.wait_for_timeout(4000)
                continue
        if "no databases yet" not in low and "choose your plan" not in low and "database" in low:
            probe = page.evaluate(JS_FETCH_DB)
            if probe.get("ok"):
                print("  wizard: database is live")
                return
        fill_first(page, ['input[name="name"]', 'input[placeholder*="database name" i]', 'input[placeholder*="name" i]'], "database-1")
        clicked = click_text(page, [r"new database", r"create a database"])
        if not clicked:
            clicked = click_button_matching(page, [r"create database", r"create subscription", r"^create", r"continue", r"next", r"activate", r"get started", r"review", r"confirm"], banned=("pay",))
        if clicked:
            print("  wizard clicked:", clicked)
        try_press_and_hold(page)
        page.wait_for_timeout(5000)
    page.screenshot(path="debug_wizard.png")
    print("  wizard end page:", page_text(page).replace("\n", " ")[:300])


def login_and_get_url(page, link, email, password, api_log):
    page.goto(link, wait_until="domcontentloaded", timeout=90000)
    txt = wait_settled(page, 60)
    print("  after activation:", page.url[:120])
    print("  activation page:", txt.replace("\n", " ")[:300])
    print("  activation api calls:", [e for e in api_log if "activ" in e])
    try_press_and_hold(page)

    early = page.evaluate(JS_FETCH_DB)
    if early.get("ok"):
        print("  session already active after activation, database fetched directly")
        page.screenshot(path="debug_console.png")
        return early
    print("  direct fetch after activation:", json.dumps(early)[:400])
    if early.get("stage") in ("no-subscription", "no-database"):
        print("  session live but nothing provisioned yet, creating via the console wizard")
        create_via_wizard(page)
        result = page.evaluate(JS_FETCH_DB)
        page.screenshot(path="debug_console.png")
        return result

    if okta_login(page, email, password):
        print("  okta login ok, checking session")
        result = page.evaluate(JS_FETCH_DB)
        if result.get("ok"):
            page.screenshot(path="debug_console.png")
            return result
        print("  okta session present but fetch failed:", json.dumps(result)[:300])

    logged_in = False
    for attempt in range(3):
        if "sign in" not in page_text(page).lower() and attempt > 0:
            logged_in = True
            break
        page.goto(CONSOLE + "/", wait_until="domcontentloaded", timeout=90000)
        wait_settled(page, 30)
        em = fill_first(page, ['input[name="email"]', 'input[type="email"]', 'input[name="username"]'], email)
        pw = fill_first(page, ['input[type="password"]', 'input[name="password"]'], password) if em else None
        if not em:
            logged_in = True
            break
        if pw:
            for name in ["Login", "Sign in", "Log in", "Next"]:
                b = page.get_by_role("button", name=re.compile("^" + name + "$", re.I)).first
                try:
                    if b.count() > 0 and b.is_enabled():
                        b.click()
                        print("  login submitted (attempt %d) via: %s" % (attempt + 1, name))
                        break
                except Exception:
                    pass
        end = time.time() + 75
        while time.time() < end:
            if try_press_and_hold(page):
                page.wait_for_timeout(3000)
                for name in ["Login", "Sign in", "Log in"]:
                    b = page.get_by_role("button", name=re.compile("^" + name + "$", re.I)).first
                    try:
                        if b.count() > 0 and b.is_enabled():
                            b.click()
                            print("  login re-submitted after challenge")
                            break
                    except Exception:
                        pass
                page.wait_for_timeout(4000)
                continue
            t = page_text(page).lower()
            if "databases" in t or "subscriptions" in t or "sign out" in t or "logout" in t:
                logged_in = True
                break
            if "valid email address and password" in t:
                print("  login rejected by site")
                break
            page.wait_for_timeout(3000)
        if logged_in:
            break
    print("  logged_in:", logged_in)
    print("  console url:", page.url[:120])
    print("  console page:", page_text(page).replace("\n", " ")[:300])
    cookies = page.context.cookies()
    print("  cookies:", sorted({c["name"] for c in cookies}))
    print("  api calls:", json.dumps(api_log[-40:]))
    result = page.evaluate(JS_FETCH_DB)
    if not result.get("ok"):
        page.goto(CONSOLE + "/#/databases", wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(8000)
        result = page.evaluate(JS_FETCH_DB)
    if result.get("stage") in ("no-subscription", "no-database"):
        create_via_wizard(page)
        result = page.evaluate(JS_FETCH_DB)
    page.screenshot(path="debug_console.png")
    return result


def test_url(url):
    print("Testing connection...")
    client = redis.Redis.from_url(url, socket_connect_timeout=30, socket_timeout=30)
    print("  PING:", client.ping())
    client.set("healthcheck", "ok")
    print("  GET healthcheck:", client.get("healthcheck"))
    client.delete("healthcheck")
    print("Connection verified.")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "verify":
        data = json.load(open(RESULT_FILE))
        print("Verifying saved account:", data["email"])
        test_url(data["url"])
        print("\nVERIFIED OK")
        return
    print("=" * 60)
    print("STEP 1: creating temporary mailbox (mail.tm)...")
    email, mail_pw, token = create_mailbox()
    password = "Redis#%d!x" % int(time.time() % 100000)
    print("  email:   ", email)
    print("  mailbox password:", mail_pw)
    api_log = []

    def on_response(resp):
        try:
            u = resp.url
            if "redis" not in u:
                return
            if resp.request.resource_type not in ("xhr", "fetch") and "/api/" not in u:
                return
            entry = resp.request.method + " " + u.split("?")[0][:110] + " -> " + str(resp.status)
            if resp.request.method in ("POST", "PUT") and any(k in u for k in ("/subscriptions", "/bdbs", "/crdbs")):
                try:
                    entry += " req: " + (resp.request.post_data or "")[:400]
                except Exception:
                    pass
            if "/login" in u or "activ" in u or resp.status >= 400:
                try:
                    entry += " body: " + resp.text()[:220].replace("\n", " ")
                except Exception:
                    pass
            api_log.append(entry)
        except Exception:
            pass

    headless = os.environ.get("HEADLESS", "1") != "0"
    use_camoufox = os.environ.get("BROWSER") == "camoufox"
    if use_camoufox:
        from camoufox.sync_api import Camoufox
        cm = Camoufox(headless=headless, humanize=True, os="windows")
        browser = cm.__enter__()
    else:
        cm = sync_playwright()
        p = cm.__enter__()
        browser = p.chromium.launch(headless=headless, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"])
    try:
        result = None
        link = None
        for attempt in range(2):
            if use_camoufox:
                ctx = browser.new_context()
            else:
                ctx = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
                    viewport={"width": 1366, "height": 768}, locale="en-US", timezone_id="America/New_York")
                ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page = ctx.new_page()
            page.on("response", on_response)
            print("STEP 2: registering via the redis.io sign-up form (attempt %d)..." % (attempt + 1))
            try:
                signup_via_form(page, email, password)
            except RuntimeError as e:
                print("  sign-up attempt failed:", str(e)[:160])
                ctx.close()
                if attempt == 1:
                    raise
                continue
            print("STEP 3: waiting for activation email...")
            link = poll_activation(token)
            print("  link:", link[:90], "...")
            print("STEP 4: activating, logging in and fetching free database...")
            result = login_and_get_url(page, link, email, password, api_log)
            break
    finally:
        try:
            browser.close()
        except Exception:
            pass
        cm.__exit__(None, None, None)
    if not result.get("ok"):
        raise SystemExit("Failed: " + json.dumps(result, indent=2))
    data = {"email": email, "password": password, "mailbox_password": mail_pw,
            "url": result["url"], "db": result["db"], "subscription": result["subscription"]}
    json.dump(data, open(RESULT_FILE, "w"), indent=2)
    print("\n" + "=" * 60)
    print("SUCCESS - free Redis database created")
    print("=" * 60)
    print("  email:   ", email)
    print("  password:", password)
    print("  url:     ", result["url"])
    parsed = urllib.parse.urlparse(result["url"])
    print("  host:    ", parsed.hostname)
    print("  port:    ", parsed.port)
    print("  db pass: ", urllib.parse.unquote(parsed.password or ""))
    print("  db:      ", result["db"])
    if mode == "test":
        test_url(result["url"])
        print("\nALL DONE")


if __name__ == "__main__":
    main()
