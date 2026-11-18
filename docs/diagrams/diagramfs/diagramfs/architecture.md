flowchart TB
  subgraph INTERNET ["Global Internet"]
    User[User Browser]
    Agent[Remote Capture Agent]
  end

  subgraph EDGE ["Edge Layer: Cloudflare"]
    WAF[Cloudflare WAF & Proxy]
    DNS[DNS Management]
  end

  subgraph AWS_CLOUD ["AWS Infrastructure"]
    subgraph LOAD_BALANCING ["Public Entry Point"]
        ALB[Application Load Balancer]
        ACM[AWS Certificate Manager - SSL/TLS]
    end

    subgraph VPC ["Virtual Private Cloud (VPC)"]
        subgraph EC2_VPS ["AWS EC2 Instance"]
            direction TB
            NGINX([Reverse Proxy: Nginx Docker])
            
            subgraph DOCKER_NET ["Docker Network"]
                direction TB
                FE[Frontend Container: React]
                subgraph Backend Container
                  BE[Backend: Flask API]
                  WS[WebSocket: SocketIO]
                  ML[ML Model]
                end 
            end
        end

        subgraph DATA_LAYER ["Data & Persistence Layer"]
            DB[(RDS: Managed PostgreSQL)]
            REDIS[(Elasticache: Redis)]
            S3[(S3: Object Storage)]
        end
    end
    
    FW_SYNC[Firewall Sync Service]
  end

  subgraph CUSTOMER_SITE ["Customer Infrastructure"]
    direction TB
    L_FW[Local Firewall: UFW / Snort]
    L_AGENT[Capture Agent Service]
    L_AGENT -.->|1. Inspect Packets| L_FW
    L_AGENT -->|2. Manage Rules| L_FW
  end

  %% Traffic Flows
  User -->|HTTPS| DNS
  DNS --> WAF
  WAF -->|Proxy/WAF Protection| ALB
  ALB -.- ACM
  ALB -->|Port 80/443| NGINX

  NGINX -->|Reverse Proxy| FE
  NGINX -->|Reverse Proxy| BE
  NGINX -->|Reverse Proxy| WS

  BE --> DB
  BE --> S3
  WS --> REDIS
  BE --> REDIS

  %% Agent Connectivity
  L_AGENT -->|Socket.IO /ws/inference| ALB
  ALB --> NGINX
  NGINX --> WS
  WS <-->|Bi-directional Sync: Blocklist / Rules| L_AGENT
  
  %% Notifications
  BE -->|Push notifications| FCM[Firebase Cloud Messaging]
  FCM --> Mobile[Mobile App]

  %% ML model
  BE -->|Send Features| ML
  ML --> BE