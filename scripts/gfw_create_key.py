"""One-off helper: create a GFW Data API key via the auth API.

Run this yourself in your own terminal (`python3 scripts/gfw_create_key.py`)
so your password is only ever typed into your own shell via getpass, never
pasted into a chat or logged anywhere. Prints the resulting API key once.
"""

from __future__ import annotations

import getpass

import requests

BASE_URL = "https://data-api.globalforestwatch.org"


def main() -> None:
    email = input("GFW account email: ").strip()
    password = getpass.getpass("GFW account password (hidden): ")

    token_resp = requests.post(
        f"{BASE_URL}/auth/token",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    token_resp.raise_for_status()
    token_body = token_resp.json()

    payload = token_body.get("data", token_body)
    access_token = payload.get("access_token") or payload.get("accessToken")
    if not access_token:
        print("Unexpected token response shape, here it is raw:")
        print(token_body)
        return

    key_resp = requests.post(
        f"{BASE_URL}/auth/apikey",
        json={
            "alias": "origin",
            "organization": "solo",
            "email": email,
            "domains": [],
        },
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    key_resp.raise_for_status()
    data = key_resp.json()["data"]

    print()
    print("API key created:")
    print(data["api_key"])


if __name__ == "__main__":
    main()
