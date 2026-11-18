import json


def test_register_creates_company_user_and_country(app_context, flask_app):
    client = flask_app.test_client()
    payload = {
        "email": "new.user@securecore.com",
        "password": "strongpassword123",
        "name": "New User",
        "company": "Acme Inc",
        "phone": "+1 (555) 000-0000",
        "country": "US",
        "plan": "small",
        "payment_data": {
            "card_number": "4242424242424242",
            "card_name": "New User",
            "expiry_month": "01",
            "expiry_year": "30",
            "billing_address": "123 Main St",
            "city": "San Francisco",
            "zip_code": "94102",
        },
    }

    res = client.post(
        "/api/v1/auth/register",
        data=json.dumps(payload),
        content_type="application/json",
    )

    assert res.status_code == 201

    data = res.get_json()
    assert data["message"] == "User registered successfully"
    assert data["user"]["email"] == payload["email"]
    assert data["user"]["company_id"] is not None
    assert data["user"]["country"] == "US"

    # Verify DB state
    from app.models.user import User
    from app.models.company import Company
    from app.models.user_company_role import UserCompanyRole

    user = User.query.filter_by(email=payload["email"]).first()
    assert user is not None
    assert user.company_id is not None
    assert user.country == "US"
    assert user.role == "user"

    company = Company.query.get(user.company_id)
    assert company is not None
    assert company.name == "Acme Inc"
    assert company.phone_number == payload["phone"]

    # Prefer new users_roles mapping if present; else fall back to legacy mapping.
    try:
        from app.models.user_role import UserRole
        from app.models.role import Role

        mapping = (
            UserRole.query.join(Role, UserRole.role_id == Role.id)
            .filter(UserRole.user_id == user.id, UserRole.company_id == company.id)
            .first()
        )
        assert mapping is not None
        assert mapping.role.name == "admin"
    except Exception:
        mapping = UserCompanyRole.query.filter_by(user_id=user.id, company_id=company.id).first()
        assert mapping is not None
        assert mapping.role == "admin"
