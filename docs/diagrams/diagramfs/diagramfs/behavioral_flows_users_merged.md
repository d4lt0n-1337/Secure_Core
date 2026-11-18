# Company Users (admin / fully / limited) — Merged Mermaid Diagrams

Goal: merge the **company-user** diagrams into a single set:

- **One merged sequence diagram** (instead of 3 separate role sequences)
- **One merged activity diagram**
- **One merged state diagram**

Legend (role requirement markers):

- `[L]` = allowed for `limited` (and therefore also usable by `fully` and `admin`)
- `[F]` = allowed for `fully` + `admin`
- `[A]` = allowed for `admin` only

Notes:

- This file covers **company users only** (not Service Provider Admin `/admin/*`).
- Enforcement is treated as **implemented**: whitelist/blocklist changes notify `elf/cicflow_live.py` which applies **UFW + Snort** consistently.

---

## 1) Merged Sequence — Company Users

sequenceDiagram
autonumber
actor U as CompanyUser (admin/fully/limited)
participant UI as Company Portal
participant API as Flask API
participant DB as Database
participant FW as FirewallService(UFW)
participant ENF as cicflow_live.py

    U->>UI: Login
    UI->>API: POST /api/v1/auth/login  [L]
    API-->>UI: 200 + JWT cookies (+ csrf_token)

    U->>UI: Monitoring (alerts)
    UI->>API: GET /api/v1/alerts | GET /alerts?severity=High&page=1 | GET /alerts/recent?limit=5 | GET /alerts/stats?time_range=today  [L]
    API->>DB: alerts queries + aggregates
    DB-->>API: data
    API-->>UI: 200

    U->>UI: Notifications
    UI->>API: GET /api/v1/notifications | PUT /notifications/read-all  [L]
    UI->>API: PUT /api/v1/notifications/{id}/read | DELETE /api/v1/notifications  [F]
    API->>DB: list/mark/clear
    DB-->>API: committed
    API-->>UI: 200

    U->>UI: Lists (read)
    UI->>API: GET /api/v1/whitelist?page=1 | GET /api/v1/blocklist?page=1  [L]
    API->>DB: query by company_id
    DB-->>API: lists
    API-->>UI: 200

    U->>UI: Whitelist (write)
    UI->>API: POST /api/v1/whitelist | PATCH /whitelist/{id} | DELETE /whitelist/{id}  [F]
    API->>DB: create/update/soft-delete
    DB-->>API: committed
    API-->>UI: 201/200/409

    U->>UI: Blocklist (write)
    UI->>API: POST /api/v1/blocklist  [F]
    talt POST conflict (IP in whitelist)
    	API-->>UI: 409
    else Allowed
    	API->>FW: block_ip(company_id, ip)
    	FW-->>API: success/failure
    	API-->>UI: 201/500
    end
    UI->>API: PATCH /api/v1/blocklist/{id} | DELETE /api/v1/blocklist/{id}  [F]
    API->>DB: update reason
    DB-->>API: committed
    API-->>UI: 200
    API->>FW: unblock_ip(id, company_id)
    FW-->>API: success/failure
    API-->>UI: 200/500

    U->>UI: Enforce (after each list change)
    API->>ENF: notify allow/block event  [F]
    ENF->>FW: apply UFW + Snort rules

    U->>UI: Company settings + backup
    UI->>API: GET /api/v1/settings/company | PUT /settings/company | POST /settings/company/backup/run  [A]
    API->>DB: read/update + snapshot
    DB-->>API: committed
    API-->>UI: 200

    U->>UI: Members management
    UI->>API: GET /api/v1/members | POST /api/v1/members | PATCH /members/{id}/role | POST /members/{id}/deactivate | POST /members/{id}/activate | DELETE /members_delete/{id}  [A]
    API->>DB: list/create/update-role/activate/deactivate/delete
    DB-->>API: committed
    API-->>UI: 200/201

    U->>UI: Billing / subscription
    UI->>API: GET /api/v1/subscription  [L]
    UI->>API: POST /api/v1/subscription/cancel | POST /api/v1/subscription/resubscribe  [A]
    API->>DB: read/update subscription (+optional payment)
    DB-->>API: committed
    API-->>UI: 200

    U->>UI: Payment methods
    UI->>API: GET /api/v1/payment-methods | POST /payment-methods | PUT /payment-methods/{id}/default | DELETE /payment-methods/{id}  [A]
    API->>DB: list/add/set-default/delete
    DB-->>API: committed
    API-->>UI: 200/201

    U->>UI: API tokens
    UI->>API: GET /api/v1/tokens | POST /tokens/generate | DELETE /tokens/{id} | GET /tokens/usage  [A]
    API->>DB: list/generate/revoke/usage
    DB-->>API: committed
    API-->>UI: 200/201

    U->>UI: Reports
    UI->>API: POST /api/v1/reports/preview | POST /reports | GET /reports/list | GET /reports/download/{filename} | POST /reports/upload  [L]
    API-->>UI: 200/201

    U->>UI: Profile + supporting
    UI->>API: GET /api/v1/settings/profile | PUT /settings/profile | GET /api/v1/downloads/metadata | POST /api/v1/devices | GET /api/v1/locations/countries  [L]
    API-->>UI: 200

---

## 2) Merged Activity — Company Users

flowchart TD
A([Start]) --> B[Login: POST /auth/login [L]]
B --> C[Monitoring: alerts + stats [L]]
C --> D[Notifications: view+ack [L], clear [F]]
D --> E[Lists (read): whitelist/blocklist [L]]
E --> F{Need list write?}
F -- fully/admin --> G[Whitelist+Blocklist CRUD [F] + Enforce via cicflow]
F -- limited --> H[Skip writes (read-only)]
G --> I{Admin-only ops?}
H --> I
I -- Yes (admin) --> J[Members + Company Settings/Backup + Billing + Tokens [A]]
I -- No --> K[Reports + Profile + Supporting endpoints [L]]
J --> K
K --> Z([End])

---

## 3) Merged State — Company User Capability States

stateDiagram-v2
[*] --> SignedOut
SignedOut --> SignedIn: POST /auth/login [L]

    SignedIn --> Monitoring: alerts/stats/recent [L]
    SignedIn --> Notifications: read/ack [L]
    SignedIn --> ListsRead: GET whitelist/blocklist [L]
    SignedIn --> Reports: reports/* [L]
    SignedIn --> Profile: settings/profile [L]

    SignedIn --> ListsWrite: whitelist/blocklist CRUD [F]
    ListsWrite --> Enforcement: cicflow_live applies UFW+Snort [F]
    Enforcement --> SignedIn

    SignedIn --> AdminOps: members/settings/billing/tokens [A]
    AdminOps --> SignedIn

    SignedIn --> SignedOut: logout/JWT expired
