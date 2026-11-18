# Core Detection & Response Workflows — v2 (PlantUML)

This is a PlantUML conversion of the Mermaid sequence diagram from:
- `docs/diagrams/core_detection_response_workflows.md`

It uses **activation bars** (`activate`/`deactivate`).

---

## Sequence — Real-time Inference → Alert → Notifications → Response (PlantUML)

```plantuml
@startuml
autonumber

participant ENF as "cicflow_live.py (Enforcer)"
participant WSINF as "Socket.IO (/ws/inference)"
participant WSUI as "Socket.IO (/ws/ui)"
participant WSH as "Flask API (WS Handler)"
participant ML as "ML Inference Engine"
participant DB as "Database"
participant AS as "AlertService"
participant NS as "NotificationService"
participant FCM as "Firebase (push)"
participant UI as "Company Portal (browser)"
participant FW as "FirewallService (UFW/Snort)"

note over ENF
Live traffic captured (pcap/flow)
Build flows → extract 70 CIC-IDS2017-style features
end note

loop ENF pre-processing (per flow)
  ENF -> ENF: parse packets → flow record
  activate ENF
  ENF -> ENF: extract features[70]
  ENF -> ENF: normalize/encode → payload
  deactivate ENF
end

ENF -> WSINF: connect(auth: api_token)
activate WSINF
WSINF -> WSH: handle_connect(auth)
activate WSH
WSH -> DB: Validate APIToken + company + subscription
activate DB
DB --> WSH: token/company/subscription OK
deactivate DB
WSH -> DB: Create WebSocketSession(session_id, user_id, token_id, ip)
activate DB
DB --> WSH: committed
deactivate DB
WSH -> WSINF: join_room(company_{company_id})
WSH --> WSINF: emit connected{session_id, rate_limit}
deactivate WSH

loop per flow / interval
  ENF -> WSINF: emit inference{features[70], src/dst ip+ports, protocol, timestamp}
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
      WSH -> WSH: allow_inference() (per-user sliding window)

      alt rate limited
        WSH --> WSINF: emit inference_result{code:RATE_LIMIT}
      else allowed
        WSH -> WSH: validate features (len==Config.ML_INPUT_FEATURES, numeric, finite)

        alt invalid features
          WSH --> WSINF: emit inference_result{code:INVALID_FEATURES}
        else valid features
          WSH -> WSH: validate metadata (safe IP/ports/protocol/timestamp)

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

  alt is_attack == true
    WSH -> AS: create_alert(alert_data)
    activate AS
    AS -> DB: INSERT Alert(... raw_features)
    activate DB
    DB --> AS: committed (alert_id)
    deactivate DB
    AS -> AS: _should_auto_block?

    opt AUTO_BLOCK enabled + severity threshold met
      AS -> FW: block_ip(company_id, source_ip, reason, related_alert_id, block_type=automatic)
      activate FW
      FW -> FW: validate_ip(ip_address)
      FW -> FW: sudo ufw deny from <ip> (if UFW enabled)
      FW -> DB: INSERT BlockedIP (is_active=true)
      activate DB
      DB --> FW: committed
      deactivate DB
      deactivate FW
    end
    deactivate AS

    note over WSH
Mobile push is best-effort
end note
    WSH -> FCM: send_notification(user_id, title/body, data{alert_id,severity,attack_type,confidence})
    activate FCM
    FCM --> WSH: success/failure
    deactivate FCM

    opt severity in {high, critical}
      WSH -> DB: Query all active company users
      activate DB
      DB --> WSH: users[]
      deactivate DB

      loop for each company user
        WSH -> NS: create_notification(tenant_id=company_id, user_id, type='alert', related_alert_id)
        activate NS
        NS -> DB: INSERT Notification(is_read=false)
        activate DB
        DB --> NS: committed
        deactivate DB
        deactivate NS
      end

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
  else is_attack == false
    WSH --> WSINF: emit inference_result{is_attack:false, attack_type, severity, confidence}
  end

  deactivate WSH
end


par Browser dashboard live updates
  UI -> WSUI: connect(JWT cookie)
  activate WSUI
  WSUI -> WSH: handle_ui_connect
  activate WSH
  WSH -> DB: verify_jwt + load user + company_id
  activate DB
  DB --> WSH: ok
  deactivate DB
  WSH -> WSUI: join_room(user_{id}) and join_room(company_{company_id})
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

note over FW
Manual allow/block list changes may trigger enforcement updates (UFW + Snort)
end note

@enduml
```
