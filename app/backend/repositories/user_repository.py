from sqlalchemy.orm import Session
from app.backend.database.models import User, OAuthAccount


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, *, email: str, hashed_password: str | None = None, full_name: str | None = None, is_superuser: bool = False) -> User:
        user = User(email=email, hashed_password=hashed_password, full_name=full_name, is_superuser=is_superuser)
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def get_by_email(self, email: str) -> User | None:
        return self.db.query(User).filter(User.email == email).first()

    def get_by_id(self, user_id: int) -> User | None:
        return self.db.query(User).filter(User.id == user_id).first()

    def find_or_create_oauth(self, *, provider: str, provider_account_id: str, email: str | None, full_name: str | None = None) -> User:
        acct = (self.db.query(OAuthAccount).filter(OAuthAccount.provider == provider, OAuthAccount.provider_account_id == provider_account_id).first())
        if acct is not None:
            return self.get_by_id(acct.user_id)
        user = self.get_by_email(email) if email else None
        if user is None:
            user = self.create(email=email, hashed_password=None, full_name=full_name)
        link = OAuthAccount(user_id=user.id, provider=provider, provider_account_id=provider_account_id, email=email)
        self.db.add(link)
        self.db.commit()
        return user
