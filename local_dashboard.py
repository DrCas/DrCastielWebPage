import os
import secrets

from authlib.integrations.flask_client import OAuth
from flask import Flask, abort, redirect, request, send_from_directory, session, url_for
from dotenv import load_dotenv

from status_api import bp as status_bp


load_dotenv()


app = Flask(__name__, static_folder=".", static_url_path="")
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)

oauth = OAuth(app)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
ALLOWED_EMAILS = {
    value.strip().lower()
    for value in os.getenv("ALLOWED_EMAILS", "").split(",")
    if value.strip()
}

GOOGLE_AUTH_CONFIGURED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)
ALLOWLIST_CONFIGURED = bool(ALLOWED_EMAILS)

if GOOGLE_AUTH_CONFIGURED:
    oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

app.register_blueprint(status_bp)


def _is_authenticated() -> bool:
    return bool(session.get("user_email"))


@app.before_request
def require_authentication():
    path = request.path
    public_paths = {"/login", "/login/google", "/auth/google", "/logout", "/healthz"}
    if path in public_paths:
        return None

    if path == "/favicon.ico":
        return None

    if not _is_authenticated():
        if path.startswith("/api/"):
            return {"error": "unauthorized"}, 401
        return redirect(url_for("login"))

    return None


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/login")
def login():
    if _is_authenticated():
        return redirect(url_for("index"))

    if not GOOGLE_AUTH_CONFIGURED:
        return (
            "Google auth is not configured. Set GOOGLE_CLIENT_ID and "
            "GOOGLE_CLIENT_SECRET environment variables.",
            503,
        )

    if not ALLOWLIST_CONFIGURED:
        return (
            "ALLOWED_EMAILS is not configured. Set ALLOWED_EMAILS to one or more "
            "authorized Gmail addresses.",
            503,
        )

    return """
    <!doctype html>
    <html lang=\"en\">
      <head>
        <meta charset=\"utf-8\" />
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
        <title>DrCastiel Login</title>
      </head>
      <body style=\"font-family: system-ui, sans-serif; background:#0b0b12; color:#e9e9f4; display:grid; place-items:center; min-height:100vh; margin:0;\">
        <div style=\"max-width:480px; padding:24px; border:1px solid rgba(255,255,255,.15); border-radius:16px; background:rgba(255,255,255,.04); text-align:center;\">
          <h1 style=\"margin-top:0;\">DrCastiel Dashboard</h1>
          <p>Sign in with your Google account to continue.</p>
          <a href=\"/login/google\" style=\"display:inline-block; padding:10px 16px; border-radius:999px; text-decoration:none; font-weight:700; color:#0b0b12; background:#d8b35a;\">Sign in with Google</a>
        </div>
      </body>
    </html>
    """


@app.get("/login/google")
def login_google():
    if not GOOGLE_AUTH_CONFIGURED or not ALLOWLIST_CONFIGURED:
        abort(503)
    redirect_uri = url_for("auth_google", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@app.get("/auth/google")
def auth_google():
    if not GOOGLE_AUTH_CONFIGURED or not ALLOWLIST_CONFIGURED:
        abort(503)

    token = oauth.google.authorize_access_token()
    userinfo = token.get("userinfo") or oauth.google.userinfo(token=token)

    email = str(userinfo.get("email", "")).strip().lower()
    is_verified = bool(userinfo.get("email_verified"))

    if not email or not is_verified:
        session.clear()
        abort(403)

    if email not in ALLOWED_EMAILS:
        session.clear()
        return "This Google account is not authorized for this dashboard.", 403

    session["user_email"] = email
    session["user_name"] = userinfo.get("name") or email
    return redirect(url_for("index"))


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
def index():
    return send_from_directory(".", "index.html")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)
