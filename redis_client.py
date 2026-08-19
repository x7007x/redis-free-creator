"""Redis client for the free Redis Cloud database created earlier.

Install dependency: pip install redis

Usage:
    python3 redis_client.py ping        test connection
    python3 redis_client.py set k v     set a key
    python3 redis_client.py get k       get a key
    python3 redis_client.py keys        list all keys
    python3 redis_client.py info        server info summary
"""

import sys
import redis

URL = ("redis://default:8a6VXHHHPrxBj90Tmrssq8UbOXNJGEsJ@"
       "wall-willowy-impartial-14251.db.redis.io:16863")


def get_client():
    r = redis.from_url(URL, decode_responses=True)
    r.ping()
    return r


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd, rest = sys.argv[1], sys.argv[2:]
    r = get_client()

    if cmd == "ping":
        print("PING ->", r.ping())

    elif cmd == "set":
        if len(rest) < 2:
            print("Usage: set <key> <value>")
            sys.exit(1)
        r.set(rest[0], rest[1])
        print(f"SET {rest[0]} -> OK")

    elif cmd == "get":
        if not rest:
            print("Usage: get <key>")
            sys.exit(1)
        print(r.get(rest[0]))

    elif cmd == "keys":
        for k in r.keys("*"):
            print(k)

    elif cmd == "info":
        info = r.info()
        for key in ("redis_version", "uptime_in_seconds", "used_memory_human",
                    "connected_clients", "maxmemory_human", "db0"):
            print(f"{key}: {info.get(key)}")

    else:
        print(__doc__)


if __name__ == "__main__":
    main()
