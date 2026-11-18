# Core Detection & Response Workflows — A4 Split — v2 (PlantUML)

This is a PlantUML conversion of:
- `docs/diagrams/core_detection_response_workflows_a4_split.md`

It keeps the same participant lane names and adds **activation bars**.

---

## Part 1/2 — Enforcer Pre-processing + WS Ingest + Queue + Validation + ML (PlantUML)

```plantuml
@startuml
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

---

## Part 2/3 — Attack Handling: Alert + Auto-block + Notifications (PlantUML)

```plantuml
@startuml
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

---

## Part 3/3 — UI Dashboard Live Updates + Alerts Pull (PlantUML)

```plantuml
@startuml
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
