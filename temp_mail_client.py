"""Temp mail client built on the free mail.tm API.

Features: create a disposable address, list and search messages,
read full body with auto link extraction, and delete messages.

Usage:
    python3 temp_mail_client.py new                  create a fresh address
    python3 temp_mail_client.py check                list all messages
    python3 temp_mail_client.py check redis          search subject/from
    python3 temp_mail_client.py body <message_id>    print full body + links
    python3 temp_mail_client.py inbox                poll until mail arrives
    python3 temp_mail_client.py wipe                 delete the mailbox
"""

import re
import sys
import json
import time
import secrets
import string
import requests

BASE = "https://api.mail.tm"
CREDS_FILE = "temp_mail_creds.json"


class TempMailClient:

    def __init__(self, address=None, password=None):
        self.session = requests.Session()
        if address and password:
            self.address = address
            self.password = password
            self.login()
        else:
            self.load_creds()

    def load_creds(self):
        try:
            c = json.load(open(CREDS_FILE))
            self.address = c["address"]
            self.password = c["password"]
            self.login()
        except (FileNotFoundError, KeyError):
            print("No saved credentials. Run: python3 temp_mail_client.py new")
            sys.exit(1)

    def save_creds(self):
        json.dump({"address": self.address, "password": self.password},
                  open(CREDS_FILE, "w"), indent=2)

    def auth(self):
        return {"Authorization": f"Bearer {self.token}"}

    def login(self):
        r = self.session.post(f"{BASE}/token", json={
            "address": self.address, "password": self.password})
        r.raise_for_status()
        self.token = r.json()["token"]

    def create_address(self, name=None):
        r = self.session.get(f"{BASE}/domains")
        r.raise_for_status()
        domain = r.json()["hydra:member"][0]["domain"]
        name = name or "user" + "".join(
            secrets.choice(string.digits + string.ascii_lowercase) for _ in range(6))
        pw = "".join(secrets.choice(string.ascii_letters + string.digits + "!@#")
                     for _ in range(12))
        r = self.session.post(f"{BASE}/accounts", json={
            "address": f"{name}@{domain}", "password": pw})
        r.raise_for_status()
        self.address = f"{name}@{domain}"
        self.password = pw
        self.login()
        self.save_creds()
        return self.address, self.password

    def list_messages(self):
        r = self.session.get(f"{BASE}/messages", headers=self.auth())
        r.raise_for_status()
        return r.json().get("hydra:member", [])

    def search(self, keyword):
        kw = keyword.lower()
        return [m for m in self.list_messages()
                if kw in (m.get("subject") or "").lower()
                or kw in m.get("from", {}).get("address", "").lower()]

    def get_message(self, message_id):
        r = self.session.get(f"{BASE}/messages/{message_id}", headers=self.auth())
        r.raise_for_status()
        return r.json()

    def find_links(self, message):
        html = message.get("html") or message.get("text", "")
        if isinstance(html, list):
            html = "\n".join(html)
        return re.findall(r"https://[A-Za-z0-9./\-_%&=?:;,#]+", html)

    def delete_message(self, message_id):
        r = self.session.delete(f"{BASE}/messages/{message_id}", headers=self.auth())
        r.raise_for_status()

    def delete_account(self):
        r = self.session.delete(f"{BASE}/accounts/{self.address}", headers=self.auth())
        r.raise_for_status()


def print_messages(msgs):
    if not msgs:
        print("Inbox is empty.")
        return
    for m in msgs:
        print(f"- [{m['id']}] {m['subject'][:60]}  "
              f"from={m['from']['address']}  {m['createdAt'][:16]}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd, rest = sys.argv[1], sys.argv[2:]

    if cmd == "new":
        client = TempMailClient.__new__(TempMailClient)
        client.session = requests.Session()
        addr, pw = client.create_address()
        print(f"Created temporary mailbox:\n  address: {addr}\n  password:  {pw}")
        return

    client = TempMailClient()

    if cmd == "check":
        msgs = client.search(rest[0]) if rest else client.list_messages()
        print_messages(msgs)

    elif cmd == "body":
        if not rest:
            print("Usage: body <message_id>")
            sys.exit(1)
        m = client.get_message(rest[0])
        print("Subject:", m["subject"])
        print("From:", m["from"]["address"])
        print("Date:", m["createdAt"])
        text = m.get("text") or ""
        if isinstance(text, list):
            text = "\n".join(text)
        print(text[:3000])
        links = client.find_links(m)
        if links:
            print("\nLinks found:")
            for u in links:
                print(" ", u)

    elif cmd == "inbox":
        keyword = rest[0] if rest else None
        print(f"Polling inbox for {client.address} (Ctrl+C to stop)...")
        try:
            while True:
                msgs = client.search(keyword) if keyword else client.list_messages()
                if msgs:
                    print_messages(msgs)
                    break
                time.sleep(10)
        except KeyboardInterrupt:
            print("\nStopped.")

    elif cmd == "wipe":
        client.delete_account()
        print("Mailbox deleted.")

    else:
        print(__doc__)


if __name__ == "__main__":
    main()
