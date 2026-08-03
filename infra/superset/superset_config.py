from __future__ import annotations

import os
from datetime import datetime, timezone

import jwt
from flask import abort, redirect, request
from flask_login import login_user
from superset.extensions import appbuilder
from superset.initialization import SupersetAppInitializer


FEATURE_FLAGS = {
    "EMBEDDED_SUPERSET": True,
    "DISABLE_EMBEDDED_SUPERSET_LOGOUT": True,
}

# Embedded dashboard framing is restricted by each dashboard's allowed domains.
TALISMAN_ENABLED = False
GUEST_ROLE_NAME = "Gamma"
GUEST_TOKEN_JWT_SECRET = os.environ["GUEST_TOKEN_JWT_SECRET"]
GUEST_TOKEN_JWT_ALGO = "HS256"
GUEST_TOKEN_JWT_EXP_SECONDS = 300
CONTENT_SECURITY_POLICY_WARNING = False


class DataPilotAppInitializer(SupersetAppInitializer):
    """Adds the local portal-to-editor authentication handoff."""

    def post_init(self) -> None:
        super().post_init()

        @self.superset_app.get("/datapilot/editor-login")
        def datapilot_editor_login():
            token = request.args.get("token", "")
            try:
                claims = jwt.decode(
                    token,
                    os.environ["EDITOR_SSO_JWT_SECRET"],
                    algorithms=["HS256"],
                    audience="superset-editor",
                    issuer="datapilot",
                    options={"require": ["exp", "iat", "jti", "sub", "role"]},
                )
            except (jwt.PyJWTError, KeyError):
                abort(401)

            issued_at = datetime.fromtimestamp(claims["iat"], tz=timezone.utc)
            if claims.get("role") != "admin" or (
                datetime.now(timezone.utc) - issued_at
            ).total_seconds() > 60:
                abort(403)

            username = os.getenv("SUPERSET_EDITOR_USERNAME", "admin")
            editor = appbuilder.sm.find_user(username=username)
            if editor is None:
                abort(503)
            login_user(editor, remember=False, force=False)

            response = redirect("/dashboard/list/", code=302)
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            return response


APP_INITIALIZER = DataPilotAppInitializer
