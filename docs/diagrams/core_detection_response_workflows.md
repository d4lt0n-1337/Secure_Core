
# Core Detection & Response Workflows

This document describes the **end-to-end real-time detection and response** pipeline.

Key implementation anchors:
- WebSocket inference ingestion + UI updates: `server/app/websocket/server.py`
- Alert persistence + optional auto-block: `server/app/services/alert_service.py`
- In-app notifications: `server/app/services/notification_service.py`
- Mobile push (Firebase): `server/app/services/firebase_service.py`
- UFW blocking/unblocking: `server/app/services/firewall_service.py`

> Naming note: the participants below intentionally match the lane names from your diagram image.

---

## Sequence — Real-time Inference → Alert → Notifications → Response

```mermaid
sequenceDiagram
	autonumber
	participant ENF as cicflow_live.py (Enforcer)
	participant WSINF as Socket.IO (/ws/inference)
	participant WSUI as Socket.IO (/ws/ui)
	participant WSH as Flask API (WS Handler)
	participant ML as ML Inference Engine
	participant DB as Database
	participant AS as AlertService
	participant NS as NotificationService
	participant FCM as Firebase (push)
	participant UI as Company Portal (browser)
	participant FW as FirewallService (UFW/Snort)

	Note over ENF: Live traffic captured (pcap/flow)
	Note over ENF: Build flows → extract 70 CIC-IDS2017-style features
	loop ENF pre-processing (per flow)
		ENF->>ENF: parse packets → flow record
		ENF->>ENF: extract features[70]
		ENF->>ENF: normalize/encode → payload
	end

	ENF->>WSINF: connect(auth: api_token)
	WSINF->>WSH: handle_connect(auth)
	WSH->>DB: Validate APIToken + company + subscription
	DB-->>WSH: token/company/subscription OK
	WSH->>DB: Create WebSocketSession(session_id, user_id, token_id, ip)
	DB-->>WSH: committed
	WSH->>WSINF: join_room(company_{company_id})
	WSH-->>WSINF: emit connected{session_id, rate_limit}

	loop per flow / interval
		ENF->>WSINF: emit inference{features[70], source/dest ip+ports, protocol, timestamp}
		WSINF->>WSH: handle_inference(session_id, payload)
		alt session_id not authenticated
			WSH-->>WSINF: emit error{code:UNAUTHORIZED}
			WSH->>WSINF: disconnect
		else authenticated
			WSH->>WSH: enqueue_inference (Queue maxsize=Config.WS_MESSAGE_QUEUE_SIZE)
			alt queue full
				WSH-->>WSINF: emit inference_result{code:QUEUE_FULL}
			else enqueued
				WSH-->>WSINF: emit inference_queued{timestamp}
				WSH->>WSH: worker dequeues task
				WSH->>WSH: process_inference_request
				WSH->>WSH: allow_inference() (per-user sliding window)
				alt rate limited
					WSH-->>WSINF: emit inference_result{code:RATE_LIMIT}
				else allowed
					WSH->>WSH: validate features (length==Config.ML_INPUT_FEATURES, numeric, finite)
					alt invalid features
						WSH-->>WSINF: emit inference_result{code:INVALID_FEATURES}
					else valid features
						WSH->>WSH: validate metadata (safe IP/ports/protocol/timestamp)
						alt invalid metadata
							WSH-->>WSINF: emit inference_result{code:INVALID_METADATA}
						else valid metadata
							WSH->>ML: predict(features)
							ML-->>WSH: {is_attack, confidence, attack_type, model_name?}
							WSH->>WSH: derive severity if missing
						end
					end
				end
			end
		end

		alt is_attack == true
			WSH->>AS: create_alert(alert_data)
			AS->>DB: INSERT Alert(company_id, src/dst, protocol, type, severity, confidence, raw_features)
			DB-->>AS: committed (alert_id)
			AS->>AS: _should_auto_block?
			opt AUTO_BLOCK enabled + severity threshold met
				AS->>FW: block_ip(company_id, source_ip, reason, related_alert_id, block_type=automatic)
				FW->>FW: validate_ip(ip_address)
				FW->>FW: sudo ufw deny from <ip> (if UFW enabled)
				FW->>DB: INSERT BlockedIP (is_active=true)
				DB-->>FW: committed
			end

			Note over WSH: Mobile push is best-effort
			WSH->>FCM: send_notification(user_id, title/body, data{alert_id,severity,attack_type,confidence})
			FCM-->>WSH: success/failure

			opt severity in {high, critical}
				WSH->>DB: Query all active company users
				DB-->>WSH: users[]
				loop for each company user
					WSH->>NS: create_notification(tenant_id=company_id, user_id, type='alert', related_alert_id)
					NS->>DB: INSERT Notification(is_read=false)
					DB-->>NS: committed
				end
				WSH->>WSUI: emit notification_created(room: company_{company_id})
			end

			WSH->>WSUI: emit alert_created(room: company_{company_id})
			WSH-->>WSINF: emit inference_result{is_attack:true, attack_type, severity, confidence, alert_id}
		else is_attack == false
			WSH-->>WSINF: emit inference_result{is_attack:false, attack_type, severity, confidence}
		end
	end

	par Browser dashboard live updates
		UI->>WSUI: connect(JWT cookie)
		WSUI->>WSH: handle_ui_connect
		WSH->>DB: verify_jwt + load user + company_id
		DB-->>WSH: ok
		WSH->>WSUI: join_room(user_{id}) and join_room(company_{company_id})
		WSH-->>WSUI: emit connected
	and UI pulls alerts list
		UI->>WSH: GET /api/v1/alerts?severity=High&page=1
		WSH->>DB: Query alerts by company_id
		DB-->>WSH: page results
		WSH-->>UI: 200
	end

	Note over FW: Manual allow/block list changes may trigger enforcement updates (UFW + Snort)
```

