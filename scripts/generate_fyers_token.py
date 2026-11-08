"""Fyers Daily Access Token Generator CLI.

Automates the OAuth2 flow to generate and save FYERS_ACCESS_TOKEN into .env.
"""
from __future__ import annotations

import os
import re
import urllib.parse
import webbrowser
from dotenv import load_dotenv
from fyers_apiv3 import fyersModel

load_dotenv()


def update_env_variable(key: str, value: str, env_path: str = ".env") -> None:
    """Safely insert or update key=value in the .env file."""
    if not os.path.exists(env_path):
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")
        return

    with open(env_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    pattern = re.compile(rf"^{re.escape(key)}\s*=")
    found = False
    new_lines = []

    for line in lines:
        if pattern.match(line):
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"{key}={value}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def main():
    print("=" * 60)
    print("  TradeSense - Fyers API v3 Access Token Generator")
    print("=" * 60)

    client_id = os.getenv("FYERS_CLIENT_ID", "").strip()
    secret_key = os.getenv("FYERS_SECRET_KEY", "").strip()
    redirect_uri = os.getenv("FYERS_REDIRECT_URI", "https://trade.fyers.in/api-login/redirect-uri/index.html").strip()

    if not client_id:
        client_id = input("\nEnter your Fyers App ID / Client ID (e.g. ABCDEF-100): ").strip()
    else:
        print(f"\nUsing FYERS_CLIENT_ID from .env: {client_id}")

    if not secret_key:
        secret_key = input("Enter your Fyers Secret Key: ").strip()
    else:
        print(f"Using FYERS_SECRET_KEY from .env: {'*' * len(secret_key)}")

    # Initialize Fyers session model
    session = fyersModel.SessionModel(
        client_id=client_id,
        secret_key=secret_key,
        redirect_uri=redirect_uri,
        response_type="code",
        grant_type="authorization_code",
    )

    # Generate Auth URL
    auth_url = session.generate_authcode()
    print("\n" + "-" * 60)
    print("Opening browser for Fyers login...")
    print(auth_url)
    print("-" * 60)

    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    print("\nAfter logging in, your browser will redirect to a URL with '?auth_code=...'")
    redirected_input = input("\nPaste the full redirected URL (or just the auth_code): ").strip()

    auth_code = redirected_input
    if "auth_code=" in redirected_input:
        parsed = urllib.parse.urlparse(redirected_input)
        params = urllib.parse.parse_qs(parsed.query)
        if "auth_code" in params:
            auth_code = params["auth_code"][0]

    if not auth_code:
        print("\n[ERROR] No auth_code received. Aborting.")
        return

    session.set_token(auth_code)
    response = session.generate_token()

    if response.get("s") == "ok" and "access_token" in response:
        access_token = response["access_token"]
        print("\n[SUCCESS] Token generated successfully!")
        
        # Save to .env
        update_env_variable("FYERS_CLIENT_ID", client_id)
        update_env_variable("FYERS_SECRET_KEY", secret_key)
        update_env_variable("FYERS_ACCESS_TOKEN", access_token)
        update_env_variable("FYERS_REDIRECT_URI", redirect_uri)

        print("Saved FYERS_CLIENT_ID, FYERS_SECRET_KEY, and FYERS_ACCESS_TOKEN to .env.")
        print("You can now proceed with Phase D!")
    else:
        print(f"\n[ERROR] Failed to generate token: {response}")


if __name__ == "__main__":
    main()
