# All Sequence Diagrams — v2 (PlantUML Bundle)

This file bundles all converted **PlantUML sequence diagrams with activation bars**.

Sources included:
- `docs/diagrams/behavioral_flows_compact_sequences.md`
- `docs/diagrams/diagramfs/diagramfs/behavioral_flows_users_sequence_split.md`
- `docs/diagrams/core_detection_response_workflows.md`
- `docs/diagrams/core_detection_response_workflows_a4_split.md`

---

## 1) Behavioral Flows — Compact Sequences (PlantUML)

### 1.1 Service Provider Admin

```plantuml
@startuml
' Source: behavioral_flows_compact_sequences.md
' Diagram: Service Provider Admin — Compact Sequence

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


---

## 2) Company Users — Sequences Split for Word (PlantUML)

### 2.1 Page 1 — Auth, Monitoring, Notifications, Lists, Enforcement

```plantuml
@startuml
' Source: behavioral_flows_users_sequence_split.md
' Diagram: Page 1

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

### 2.2 Page 2 — Admin Ops, Billing, Tokens, Reports, Profile

```plantuml
@startuml
' Source: behavioral_flows_users_sequence_split.md
' Diagram: Page 2

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

---

## 4) Core Detection & Response Workflows — A4 Split (PlantUML)

### 4.1 Part 1/2

```plantuml
@startuml
' Source: core_detection_response_workflows_a4_split.md
' Diagram: Part 1/2

autonumber
participant ENF as "cicflow_live.py (Enforcer)"
participant WSINF as "Socket.IO (/ws/inference)"
participant WSH as "Flask API (WS Handler)"
participant ML as "ML Inference Engine"
participant DB as "Database"


note over ENF
Live traffic captured (pcap/flow)
end note

loop ENF pre-processing (per flow)
  ENF -> ENF: parse packets → flow record
  activate ENF
  ENF -> ENF: extract features[70] (CIC-IDS2017-style)
  ENF -> ENF: normalize/encode → payload
  deactivate ENF
end

ENF -> WSINF: connect(auth: api_token)
activate WSINF
WSINF -> WSH: handle_connect(auth)
activate WSH
WSH -> DB: Validate APIToken + company + subscription
activate DB
DB --> WSH: OK
deactivate DB
WSH -> DB: Create WebSocketSession(session_id, user_id, token_id, ip)
activate DB
DB --> WSH: committed
deactivate DB
WSH -> WSINF: join_room(company_{company_id})
WSH --> WSINF: emit connected{session_id, rate_limit}
deactivate WSH

deactivate WSINF

loop per flow / interval
  ENF -> WSINF: emit inference{features[70], src/dst ip+ports, protocol, timestamp}
  activate WSINF
  WSINF -> WSH: handle_inference(session_id, payload)
  activate WSH

  alt session_id not authenticated
    WSH --> WSINF: emit error{code:UNAUTHORIZED}
    WSH -> WSINF: disconnect
  else authenticated
    WSH -> WSH: enqueue_inference (Queue maxsize=Config.WS_MESSAGE_QUEUE_SIZE)

    alt queue full
      WSH --> WSINF: emit inference_result{code:QUEUE_FULL}
    else enqueued
      WSH --> WSINF: emit inference_queued{timestamp}
      WSH -> WSH: worker dequeues task
      WSH -> WSH: process_inference_request
      WSH -> WSH: allow_inference() (sliding window)

      alt rate limited
        WSH --> WSINF: emit inference_result{code:RATE_LIMIT}
      else allowed
        WSH -> WSH: validate features (len==Config.ML_INPUT_FEATURES, finite)

        alt invalid features
          WSH --> WSINF: emit inference_result{code:INVALID_FEATURES}
        else valid features
          WSH -> WSH: validate metadata (safe ip/ports/protocol/timestamp)

          alt invalid metadata
            WSH --> WSINF: emit inference_result{code:INVALID_METADATA}
          else valid metadata
            WSH -> ML: predict(features)
            activate ML
            ML --> WSH: {is_attack, confidence, attack_type, model_name?}
            deactivate ML
            WSH -> WSH: derive severity if missing
          end
        end
      end
    end
  end

  deactivate WSH
  deactivate WSINF
end

@enduml
```

### 4.2 Part 2/3

```plantuml
@startuml
' Source: core_detection_response_workflows_a4_split.md
' Diagram: Part 2/2

autonumber
participant ENF as "cicflow_live.py (Enforcer)"
participant WSINF as "Socket.IO (/ws/inference)"
participant WSUI as "Socket.IO (/ws/ui)"
participant WSH as "Flask API (WS Handler)"
participant DB as "Database"
participant AS as "AlertService"
participant NS as "NotificationService"
participant FCM as "Firebase (push)"
participant FW as "FirewallService (UFW/Snort)"

note over WSH
Continuation after Part 1 result
end note

alt is_attack == true
  activate WSH
  WSH -> AS: create_alert(alert_data)
  activate AS
  AS -> DB: INSERT Alert(...)
  activate DB
  DB --> AS: committed (alert_id)
  deactivate DB

  opt AUTO_BLOCK (enabled + threshold)
    AS -> FW: block_ip(company_id, source_ip, related_alert_id)
    activate FW
    FW -> FW: validate_ip + apply UFW deny + persist BlockedIP
    FW --> AS: success/failure
    deactivate FW
  end
  deactivate AS

  note over WSH
Mobile push is best-effort
end note
  WSH -> FCM: send_notification(best-effort){alert_id,severity,attack_type,confidence}
  activate FCM
  FCM --> WSH: success/failure
  deactivate FCM

  opt severity in {high, critical}
    WSH -> NS: create_notifications_for_company(company_id, related_alert_id)
    activate NS
    NS -> DB: bulk INSERT Notification rows (active users)
    activate DB
    DB --> NS: committed
    deactivate DB
    deactivate NS
    WSH -> WSUI: emit notification_created(room: company_{company_id})
    activate WSUI
    WSUI --> WSH: delivered
    deactivate WSUI
  end

  WSH -> WSUI: emit alert_created(room: company_{company_id})
  activate WSUI
  WSUI --> WSH: delivered
  deactivate WSUI

  WSH --> WSINF: emit inference_result{is_attack:true, attack_type, severity, confidence, alert_id}
  deactivate WSH
else is_attack == false
  WSH --> WSINF: emit inference_result{is_attack:false, attack_type, severity, confidence}
end

note over FW
Manual allow/block list changes may trigger enforcement updates (UFW + Snort)
end note

@enduml
```

### 4.3 Part 3/3

```plantuml
@startuml
' Source: core_detection_response_workflows_a4_split.md
' Diagram: Part 3/3

autonumber
participant ENF as "cicflow_live.py (Enforcer)"
participant WSUI as "Socket.IO (/ws/ui)"
participant WSH as "Flask API (WS Handler)"
participant DB as "Database"
participant UI as "Company Portal (browser)"

note over WSH
This part focuses on the Company Portal consuming updates.
end note

par Browser dashboard live updates
  UI -> WSUI: connect + authenticate (JWT cookie)
  activate WSUI
  WSUI -> WSH: handle_ui_connect
  activate WSH
  WSH -> DB: verify_jwt + resolve company rooms
  activate DB
  DB --> WSH: ok
  deactivate DB
  WSH -> WSUI: join_room(user_{id}, company_{company_id})
  WSH --> WSUI: emit connected
  deactivate WSH
  deactivate WSUI
else UI pulls alerts list
  UI -> WSH: GET /api/v1/alerts?severity=High&page=1
  activate WSH
  WSH -> DB: Query alerts by company_id
  activate DB
  DB --> WSH: page results
  deactivate DB
  WSH --> UI: 200
  deactivate WSH
end

@enduml
```
