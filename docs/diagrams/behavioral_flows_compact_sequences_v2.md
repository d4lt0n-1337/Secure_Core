# Behavioral Flows — Compact Sequence Diagrams (A4) — v2 (PlantUML)

This is a PlantUML conversion of the Mermaid sequence diagrams from:
- `docs/diagrams/behavioral_flows_compact_sequences.md`

It uses **activation bars** (`activate`/`deactivate`) for readability.

---

## 1) Service Provider Admin — Compact Sequence (PlantUML)

```plantuml
@startuml
autonumber

actor SPA as "ServiceProviderAdmin"
participant UI as "Admin Portal"
participant API as "Flask API"
participant DB as "Database"
participant WS as "Socket.IO"
participant FCM as "Firebase"

SPA -> UI: Open Admin (companies)
activate UI
UI -> API: GET /api/v1/admin/users
activate API
API -> API: @admin_required
API -> DB: companies+members+subscription+counts
activate DB
DB --> API: users+pagination
deactivate DB
API --> UI: 200
deactivate API

deactivate UI

SPA -> UI: Company + subscription
activate UI
UI -> API: GET /api/v1/admin/companies/{company_id}
activate API
API -> DB: company+alerts_count+subscription
activate DB
DB --> API: company
deactivate DB
API --> UI: 200

UI -> API: PUT /api/v1/admin/companies/{company_id}/subscription
API -> DB: upsert/downgrade
activate DB
DB --> API: committed
deactivate DB
API --> UI: 200

UI -> API: POST /api/v1/admin/companies/{company_id}/subscription/cancel
API -> DB: delete subscription + delete tokens
activate DB
DB --> API: committed
deactivate DB
API --> UI: 200

deactivate API
deactivate UI

SPA -> UI: User ops (lifecycle)
activate UI
UI -> API: PUT /api/v1/admin/users/{user_id}/suspend | /activate | PUT /users/{user_id} | DELETE /users/{user_id}
activate API
API -> DB: is_active toggle / update / delete
activate DB
DB --> API: committed
deactivate DB
API --> UI: 200
deactivate API
deactivate UI

SPA -> UI: Platform status
activate UI
UI -> API: GET /api/v1/admin/stats | GET /api/v1/admin/health
activate API
API -> DB: aggregates / health snapshot
activate DB
DB --> API: payload
deactivate DB
API --> UI: 200
deactivate API
deactivate UI

SPA -> UI: Roles
activate UI
UI -> API: GET /api/v1/admin/roles | PUT /api/v1/admin/users/{user_id}/company-role
activate API
API -> DB: list roles / upsert mapping
activate DB
DB --> API: committed
deactivate DB
API --> UI: 200
deactivate API
deactivate UI

SPA -> UI: Broadcast
activate UI
UI -> API: POST /api/v1/admin/notifications/send
activate API
API -> DB: Notification rows + AdminBroadcast
activate DB
DB --> API: committed
deactivate DB
API -> WS: emit notification_created
activate WS
WS --> API: ack
deactivate WS
API -> FCM: push
activate FCM
FCM --> API: success/failure
deactivate FCM
API --> UI: 201

deactivate API

UI -> API: GET /api/v1/admin/notifications/history
activate API
API -> DB: history
activate DB
DB --> API: history
deactivate DB
API --> UI: 200
deactivate API

deactivate UI
@enduml
```
