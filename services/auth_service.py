from flask import current_app, g, session
from werkzeug.security import check_password_hash, generate_password_hash

from models import User, db


class AuthService:
    @staticmethod
    def login_disabled():
        return bool(current_app.config.get("LOGIN_DISABLED"))

    @classmethod
    def ensure_default_user(cls):
        username = current_app.config.get("DEFAULT_ADMIN_USERNAME", "admin")
        password = current_app.config.get("DEFAULT_ADMIN_PASSWORD", "admin123")
        display_name = current_app.config.get("DEFAULT_ADMIN_DISPLAY_NAME", "系统管理员")
        user = User.query.filter_by(username=username).first()
        if user:
            return user
        user = User(
            username=username,
            display_name=display_name,
            role="admin",
            password_hash=generate_password_hash(password),
        )
        db.session.add(user)
        db.session.commit()
        return user

    @staticmethod
    def authenticate(username: str, password: str):
        user = User.query.filter_by(username=str(username or "").strip()).first()
        if not user or not user.is_active:
            return None
        if not check_password_hash(user.password_hash, str(password or "")):
            return None
        return user

    @staticmethod
    def login_user(user: User):
        session.clear()
        session["user_id"] = user.id
        session["user_display_name"] = user.display_name

    @staticmethod
    def logout_user():
        session.clear()

    @classmethod
    def is_admin(cls, user: User | None = None):
        if cls.login_disabled():
            return True
        user = user or cls.current_user()
        return bool(user and user.role == "admin")

    @staticmethod
    def current_user():
        user_id = session.get("user_id")
        if not user_id:
            return None
        user = getattr(g, "_current_user", None)
        if user is None:
            user = User.query.get(user_id)
            if user and not user.is_active:
                session.clear()
                return None
            g._current_user = user
        return user

    @staticmethod
    def update_password(user: User, new_password: str):
        user.password_hash = generate_password_hash(str(new_password or ""))
        db.session.commit()

    @classmethod
    def uses_initial_password(cls, user: User | None = None):
        if cls.login_disabled():
            return False
        user = user or cls.current_user()
        if not user:
            return False
        default_username = current_app.config.get("DEFAULT_ADMIN_USERNAME", "admin")
        default_password = current_app.config.get("DEFAULT_ADMIN_PASSWORD", "admin123")
        return user.username == default_username and check_password_hash(user.password_hash, str(default_password or ""))

    @classmethod
    def can_manage_course(cls, course):
        if cls.login_disabled():
            return True
        user = cls.current_user()
        if not user:
            return False
        if cls.is_admin(user):
            return True
        return course.owner_user_id in (None, user.id)
