"""EventBridge → Lambda: send daily Telegram message with Upstox auth URL."""

import boto3
import json
import os
import urllib.parse
import urllib.request

APP_NAME = os.environ.get("APP_NAME", "gex-alerts")
REGION = os.environ.get("AWS_REGION", "ap-south-1")
UPSTOX_AUTH_URL = "https://api.upstox.com/v2/login/authorization/dialog"

ssm = boto3.client("ssm", region_name=REGION)


def _get_param(name: str, encrypted: bool = True) -> str:
    return ssm.get_parameter(
        Name=f"/{APP_NAME}/{name}", WithDecryption=encrypted
    )["Parameter"]["Value"]


def handler(event, context):
    api_key = _get_param("UPSTOX_API_KEY")
    redirect_uri = _get_param("UPSTOX_REDIRECT_URI", encrypted=False)
    bot_token = _get_param("TELEGRAM_BOT_TOKEN")
    chat_id = _get_param("TELEGRAM_CHAT_ID", encrypted=False)

    auth_url = (
        f"{UPSTOX_AUTH_URL}?"
        + urllib.parse.urlencode({
            "client_id": api_key,
            "redirect_uri": redirect_uri,
            "response_type": "code",
        })
    )

    message = (
        "🔑 <b>Daily Upstox Authorization</b>\n\n"
        "Market opens in ~25 minutes.\n\n"
        f'<a href="{auth_url}">Tap here to authorize Upstox →</a>\n\n'
        "Token is auto-saved after you authorize."
    )

    payload = json.dumps({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }).encode()

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read())

    return {"status": "sent", "message_id": result.get("result", {}).get("message_id")}
