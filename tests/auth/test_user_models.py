from app.backend.database.models import User, OAuthAccount

def test_user_columns():
    cols = {c.name for c in User.__table__.columns}
    assert {"id", "email", "hashed_password", "full_name", "is_active", "is_superuser", "created_at"} <= cols

def test_oauth_unique_constraint():
    uqs = [c for c in OAuthAccount.__table__.constraints
           if "provider" in {col.name for col in getattr(c, "columns", [])}]
    assert uqs, "expected a unique constraint over (provider, provider_account_id)"
