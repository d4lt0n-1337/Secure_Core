# Company Users — Sequence Diagrams (Split for Word) — v2 (PlantUML)

This is a PlantUML conversion of:
- `docs/diagrams/diagramfs/diagramfs/behavioral_flows_users_sequence_split.md`

It adds **activation bars** and preserves permission markers `[L] [F] [A]`.

---

## Page 1 — Auth, Monitoring, Notifications, Lists, Enforcement (PlantUML)

```plantuml
@startuml
autonumber

actor U as "CompanyUser (admin/fully/limited)"
participant UI as "Company Portal"
participant API as "Flask API"
participant DB as "Database"
participant FW as "FirewallService(UFW)"
participant ENF as "cicflow_live.py"

U -> UI: Login
activate UI
UI -> API: POST /api/v1/auth/login  [L]
activate API
API --> UI: 200 + JWT cookies (+ csrf_token)
deactivate API

deactivate UI

U -> UI: Monitoring (alerts)
activate UI
UI -> API: GET /api/v1/alerts | GET /alerts?severity=High&page=1 | GET /alerts/recent?limit=5 | GET /alerts/stats?time_range=today  [L]
activate API
API -> DB: alerts queries + aggregates
activate DB
DB --> API: data
deactivate DB
API --> UI: 200
deactivate API

deactivate UI

U -> UI: Notifications
activate UI
UI -> API: GET /api/v1/notifications | PUT /notifications/read-all  [L]
activate API
API -> DB: list/mark
activate DB
DB --> API: committed
deactivate DB
API --> UI: 200
deactivate API

deactivate UI

U -> UI: Notifications (write)
activate UI
UI -> API: PUT /api/v1/notifications/{id}/read | DELETE /api/v1/notifications  [F]
activate API
API -> DB: mark/clear
activate DB
DB --> API: committed
deactivate DB
API --> UI: 200
deactivate API

deactivate UI

U -> UI: Lists (read)
activate UI
UI -> API: GET /api/v1/whitelist?page=1 | GET /api/v1/blocklist?page=1  [L]
activate API
API -> DB: query by company_id
activate DB
DB --> API: lists
deactivate DB
API --> UI: 200
deactivate API

deactivate UI

U -> UI: Whitelist (write)
activate UI
UI -> API: POST /api/v1/whitelist | PATCH /whitelist/{id} | DELETE /whitelist/{id}  [F]
activate API
API -> DB: create/update/soft-delete
activate DB
DB --> API: committed
deactivate DB
API --> UI: 201/200/409
deactivate API

deactivate UI

U -> UI: Blocklist (write)
activate UI
UI -> API: POST /api/v1/blocklist  [F]
activate API
alt POST conflict (IP in whitelist)
  API --> UI: 409
else Allowed
  API -> FW: block_ip(company_id, ip)
  activate FW
  FW --> API: success/failure
  deactivate FW
  API --> UI: 201/500
end

deactivate API
deactivate UI

U -> UI: Blocklist (update/delete)
activate UI
UI -> API: PATCH /api/v1/blocklist/{id} | DELETE /api/v1/blocklist/{id}  [F]
activate API
API -> DB: update reason
activate DB
DB --> API: committed
deactivate DB
API --> UI: 200
API -> FW: unblock_ip(id, company_id)
activate FW
FW --> API: success/failure
deactivate FW
API --> UI: 200/500
deactivate API

deactivate UI

U -> UI: Enforce (after each list change)
activate UI
API -> ENF: notify allow/block event  [F]
activate ENF
ENF -> FW: apply UFW + Snort rules
activate FW
FW --> ENF: applied
deactivate FW
ENF --> API: ack
deactivate ENF

deactivate UI
@enduml
```

---

## Page 2 — Admin Ops, Billing, Tokens, Reports, Profile (PlantUML)

```plantuml
@startuml
autonumber

actor U as "CompanyUser (admin/fully/limited)"
participant UI as "Company Portal"
participant API as "Flask API"
participant DB as "Database"

U -> UI: Company settings + backup
activate UI
UI -> API: GET /api/v1/settings/company | PUT /settings/company | POST /settings/company/backup/run  [A]
activate API
API -> DB: read/update + snapshot
activate DB
DB --> API: committed
deactivate DB
API --> UI: 200
deactivate API

deactivate UI

U -> UI: Members management
activate UI
UI -> API: GET /api/v1/members | POST /api/v1/members | PATCH /members/{id}/role | POST /members/{id}/deactivate | POST /members/{id}/activate | DELETE /members_delete/{id}  [A]
activate API
API -> DB: list/create/update-role/activate/deactivate/delete
activate DB
DB --> API: committed
deactivate DB
API --> UI: 200/201
deactivate API

deactivate UI

U -> UI: Billing / subscription
activate UI
UI -> API: GET /api/v1/subscription  [L]
activate API
API --> UI: 200
deactivate API

UI -> API: POST /api/v1/subscription/cancel | POST /api/v1/subscription/resubscribe  [A]
activate API
API -> DB: read/update subscription (+optional payment)
activate DB
DB --> API: committed
deactivate DB
API --> UI: 200
deactivate API

deactivate UI

U -> UI: Payment methods
activate UI
UI -> API: GET /api/v1/payment-methods | POST /payment-methods | PUT /payment-methods/{id}/default | DELETE /payment-methods/{id}  [A]
activate API
API -> DB: list/add/set-default/delete
activate DB
DB --> API: committed
deactivate DB
API --> UI: 200/201
deactivate API

deactivate UI

U -> UI: API tokens
activate UI
UI -> API: GET /api/v1/tokens | POST /tokens/generate | DELETE /tokens/{id} | GET /tokens/usage  [A]
activate API
API -> DB: list/generate/revoke/usage
activate DB
DB --> API: committed
deactivate DB
API --> UI: 200/201
deactivate API

deactivate UI

U -> UI: Reports
activate UI
UI -> API: POST /api/v1/reports/preview | POST /reports | GET /reports/list | GET /reports/download/{filename} | POST /reports/upload  [L]
activate API
API --> UI: 200/201
deactivate API

deactivate UI

U -> UI: Profile + supporting
activate UI
UI -> API: GET /api/v1/settings/profile | PUT /settings/profile | GET /api/v1/downloads/metadata | POST /api/v1/devices | GET /api/v1/locations/countries  [L]
activate API
API --> UI: 200
deactivate API

deactivate UI
@enduml
```
