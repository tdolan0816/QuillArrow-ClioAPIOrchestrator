"""
Authentication module for the Clio API Orchestrator.

Current implementation: simple username/password dict + JWT tokens.
Future: swap in MS Entra (Azure AD) OAuth without changing the rest of the app.

How it works:
    1. User sends POST /api/auth/login with {"username": "...", "password": "..."}
    2. Server verifies against the USERS dict and returns a JWT access token
    3. All subsequent requests include the token in the Authorization header
    4. The `get_current_user` dependency extracts and verifies the token

JWT tokens expire after ACCESS_TOKEN_EXPIRE_MINUTES (default 480 = 8 hours,
a full workday). Users re-login when the token expires.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

# ── Configuration ────────────────────────────────────────────────────────────
# In production, move SECRET_KEY to .env. For now it's here for simplicity.
SECRET_KEY = "clio-orchestrator-dev-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8 hours (one workday)

# ── User Store ───────────────────────────────────────────────────────────────
# Simple dict of authorized users. Passwords are bcrypt-hashed.
#
# To add a user, add an entry below. The dict KEY is just a label; what the
# person types into the login form is matched against the inner "username"
# value (case-insensitive), so an email address works as a username. The
# password is hashed at startup from the plain text given to pwd_context.hash().
#
# When you move to MS Entra, this entire section gets replaced with
# Azure AD token verification — the rest of the file stays the same.

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

USERS = {
    "admin": {
        "username": "admin",
        "full_name": "Admin User",
        "hashed_password": pwd_context.hash("ClioAdmin2025!"),
        "role": "admin",
    },
    "clio_user": {
        "username": "clio_user",
        "full_name": "Clio Super User",
        "hashed_password": pwd_context.hash("ClioUser2025!"),
        "role": "user",
    },
    "Cody_Spencer": {
        "username": "cpencer@quillarrow.com",
        "full_name": "Cody Spencer",
        "hashed_password": pwd_context.hash("ClioUser0001!"),
        "role": "user",
    },
}

# ── Models ───────────────────────────────────────────────────────────────────

class Token(BaseModel):
    """Response model for the login endpoint."""
    access_token: str
    token_type: str
    username: str
    role: str
    expires_in_minutes: int


class UserInfo(BaseModel):
    """Represents the authenticated user extracted from a JWT token."""
    username: str
    full_name: str
    role: str


# ── Token Utilities ──────────────────────────────────────────────────────────

# OAuth2PasswordBearer tells FastAPI where to find the token.
# tokenUrl must match the login endpoint path.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check a plain password against a bcrypt hash."""
    return pwd_context.verify(plain_password, hashed_password)


def find_user(username: str | None) -> dict | None:
    """
    Find a user by the ``username`` value stored on each USERS entry.

    Matching is case-insensitive and whitespace-tolerant so that
    "CSpencer@QuillArrow.com " logs in the same as "cspencer@quillarrow.com".
    The dict key is deliberately NOT used for lookup — it's only a label — so
    entries can be keyed by a readable name while the login is an email.
    """
    if not username:
        return None
    needle = username.strip().lower()
    for user in USERS.values():
        if (user.get("username") or "").strip().lower() == needle:
            return user
    return None


def authenticate_user(username: str, password: str) -> dict | None:
    """
    Look up a user by username and verify their password.
    Returns the user dict if valid, None otherwise.
    """
    user = find_user(username)
    if not user:
        return None
    if not verify_password(password, user["hashed_password"]):
        return None
    return user


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """
    Create a signed JWT token with the given payload.
    The token includes an expiration time (exp claim).
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme)) -> UserInfo:
    """
    FastAPI dependency that extracts and verifies the JWT from the
    Authorization header. Returns a UserInfo object.

    Usage in any route:
        @router.get("/protected")
        def my_route(user: UserInfo = Depends(get_current_user)):
            print(f"Request from {user.username}")

    Raises 401 if the token is missing, expired, or invalid.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token. Please log in again.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # Decode the JWT and extract the username
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str | None = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    # Verify the user still exists in our user store (matched on the
    # "username" value, same as login — not on the dict key).
    user = find_user(username)
    if user is None:
        raise credentials_exception

    return UserInfo(
        username=user["username"],
        full_name=user["full_name"],
        role=user["role"],
    )


# ── Auth Router (endpoints) ─────────────────────────────────────────────────

auth_router = APIRouter(tags=["Authentication"])


@auth_router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    Authenticate a user and return a JWT access token.

    Send a POST request with form data:
        username: the username
        password: the password

    Returns a JWT token that must be included in all subsequent requests
    as: Authorization: Bearer <token>
    """
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create a JWT with the username as the "sub" (subject) claim
    access_token = create_access_token(data={"sub": user["username"]})

    return Token(
        access_token=access_token,
        token_type="bearer",
        username=user["username"],
        role=user["role"],
        expires_in_minutes=ACCESS_TOKEN_EXPIRE_MINUTES,
    )


@auth_router.get("/me", response_model=UserInfo)
def get_me(current_user: UserInfo = Depends(get_current_user)):
    """
    Return the profile of the currently authenticated user.
    Useful for the frontend to display who is logged in.
    """
    return current_user
