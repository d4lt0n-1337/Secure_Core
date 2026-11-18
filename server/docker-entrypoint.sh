#!/bin/bash
set -e

echo "=== SecureCore IDS — Docker Entrypoint ==="

# Initialize database schema + seed on first run
if [ "$DATABASE_URL" ]; then
    echo "DATABASE_URL is set, initializing database schema..."
    python -c "
import hashlib
from app import create_app
from app.extensions import db
from datetime import date, timedelta

app = create_app('production')
with app.app_context():
    # Create all tables (idempotent — safe to run multiple times)
    db.create_all()
    print('  Tables created/verified.')

    # Seed minimal data if needed
    from app.models.company import Company
    from app.models.subscription import Subscription
    from app.models.user import User
    from app.models.user_company_role import UserCompanyRole
    from config import Config

    company = Company.query.filter_by(name='SecureCore Admin').first()
    if not company:
        company = Company(public_id=Company.generate_public_id(), name='SecureCore Admin')
        db.session.add(company)
        db.session.flush()
        print('  Created company: SecureCore Admin')

    admin = User.query.filter_by(email=Config.DEFAULT_ADMIN_EMAIL).first()
    if not admin:
        admin = User(
            company_id=company.id,
            email=Config.DEFAULT_ADMIN_EMAIL,
            name='Administrator',
            role='admin',
            is_active=True,
            email_verified=True,
        )
        admin.set_password(Config.DEFAULT_ADMIN_PASSWORD)
        db.session.add(admin)
        db.session.flush()
        print(f'  Created admin: {Config.DEFAULT_ADMIN_EMAIL}')

    ucr = UserCompanyRole.query.filter_by(user_id=admin.id, company_id=company.id).first()
    if not ucr:
        db.session.add(UserCompanyRole(user_id=admin.id, company_id=company.id, role='admin'))

    sub = Subscription.query.filter_by(company_id=company.id).first()
    if not sub:
        sub = Subscription(
            company_id=company.id,
            plan_name='Small Companies',
            plan_price=49.00,
            status='active',
            start_date=date.today(),
            end_date=date.today() + timedelta(days=365),
            next_billing_date=date.today() + timedelta(days=30),
            max_requests_per_minute=1000,
            max_requests_per_month=1_000_000,
        )
        db.session.add(sub)
        print('  Created subscription.')

    # Generate and seed a new API token for stress testing
    from app.models.token import APIToken
    import secrets
    token_random = secrets.token_urlsafe(48)
    token_str = f'sk_live_securecore_{token_random}'
    token_hash = hashlib.sha256(token_str.encode()).hexdigest()
    existing = APIToken.query.filter_by(name='Stress Test Token').first()
    if not existing:
        api_token = APIToken(
            company_id=company.id,
            token_hash=token_hash,
            token_prefix=token_str[:20],
            name='Stress Test Token',
            expires_at=date.today() + timedelta(days=365)
        )
        db.session.add(api_token)
        print(f'  Created API token for stress testing.')
        print(f'  TOKEN={token_str}')

    db.session.commit()
    print('  Database initialized successfully.')
" 2>&1 || echo "WARNING: DB init failed (may already be initialized)"
fi

echo "Starting gunicorn..."
exec "$@"
