"""API Gateway → Lambda: capture Upstox OAuth code, exchange for token, store in SSM."""

import boto3
import json
import os
import urllib.parse
import urllib.request

APP_NAME = os.environ.get("APP_NAME", "gex-alerts")
REGION = os.environ.get("AWS_REGION", "ap-south-1")
UPSTOX_TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"

ssm = boto3.client("ssm", region_name=REGION)


def _get_param(name: str, encrypted: bool = True) -> str:
    return ssm.get_parameter(
        Name=f"/{APP_NAME}/{name}", WithDecryption=encrypted
    )["Parameter"]["Value"]


def handler(event, context):
    params = event.get("queryStringParameters") or {}
    code = params.get("code")

    if not code:
        error = params.get("error", "unknown")
        return _html(400, f"<h2>Authorization failed: {error}</h2>")

    # Read app credentials from SSM
    api_key = _get_param("UPSTOX_API_KEY")
    api_secret = _get_param("UPSTOX_API_SECRET")
    redirect_uri = _get_param("UPSTOX_REDIRECT_URI", encrypted=False)

    # Exchange authorization code for access token
    body = urllib.parse.urlencode({
        "code": code,
        "client_id": api_key,
        "client_secret": api_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode()

    req = urllib.request.Request(
        UPSTOX_TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        return _html(502, f"<h2>Token exchange failed: {exc}</h2>")

    token = data.get("access_token", "")
    if not token:
        return _html(500, "<h2>No access_token in Upstox response.</h2>")

    # Store fresh token in SSM (EC2 reads this at next startup)
    ssm.put_parameter(
        Name=f"/{APP_NAME}/UPSTOX_ACCESS_TOKEN",
        Value=token,
        Type="SecureString",
        Overwrite=True,
    )

    return _html(
        200,
        (
            "<h2>✅ Upstox authorized!</h2>"
            "<p>Token saved. GEX Alerts will use it at next market open.</p>"
            "<p>You can close this tab.</p>"
        ),
    )


def _html(status: int, body: str) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "text/html"},
        "body": f'<html><body style="font-family:sans-serif;padding:40px">{body}</body></html>',
    }
