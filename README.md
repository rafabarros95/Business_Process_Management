# Project Scope

## Camunda 8 Business Process Management Project

This repository contains a Business Process Management (BPM) project built with **Camunda 8**.

## Process to explore

We will explore a **bicycle manufacturing** process using the reference project below:

https://github.com/BpaLabTHCologne/bpa_lab_demonstration_factory

## Project goal

The goal of this work is to analyse the current or potential use of **AI** to improve a specific process within the bicycle manufacturing workflow.

The exact process to improve is still to be decided.

# Camunda 8 Local Setup — Prerequisites

This document describes the requirements and steps to run Camunda 8 locally using Docker, as used in this project.

---

## System Requirements

| Component | Version | Notes |
|---|---|---|
| OS | Windows 10/11 | macOS and Linux also supported |
| Docker Desktop | 20.10.21+ | Must be running before starting Camunda |
| Python | 3.9+ | 3.12 recommended |
| uv _(package manager)_ | any | Optional, can use pip instead |

> **Note:** Camunda 8 Run (the non-Docker alternative) requires Java 21–23. If you prefer that route, install [Temurin JDK 21](https://adoptium.net/temurin/releases/?version=21) and set `JAVA_HOME` accordingly. This project uses the **Docker path**, so Java is not required.

---

## 1. Install Docker Desktop

Download and install Docker Desktop from [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop).

After installation, start Docker Desktop and wait for the whale icon in the system tray to stop animating (engine is ready).

Verify in PowerShell:

```powershell
docker --version
docker ps
```

---

## 2. Download Camunda 8 Docker Compose

Since Camunda 8.7, the official Docker Compose files are distributed via [`camunda/camunda-distributions`](https://github.com/camunda/camunda-distributions/releases).

```powershell
# Create project folder
mkdir C:\camunda8
cd C:\camunda8

# Download the 8.7 compose bundle
Invoke-WebRequest -Uri "https://github.com/camunda/camunda-distributions/releases/download/docker-compose-8.7/docker-compose-8.7.zip" -OutFile "docker-compose-8.7.zip"

# Extract
Expand-Archive -Path "docker-compose-8.7.zip" -DestinationPath "C:\camunda8"
```

The extracted folder contains:

| File | Description |
|---|---|
| `docker-compose.yaml` | Full stack (includes Keycloak, Optimize, Web Modeler) |
| `docker-compose-core.yaml` | Lightweight: Zeebe + Operate + Tasklist + Connectors |
| `docker-compose-web-modeler.yaml` | Web Modeler standalone |
| `.env` | Environment variables used by the compose files |

---

## 3. Start Camunda 8 (Core Stack)

```powershell
cd C:\camunda8
docker compose -f docker-compose-core.yaml up -d
```

Wait ~2 minutes for all services to become healthy, then verify:

```powershell
docker compose -f docker-compose-core.yaml ps
```

All containers should show `(healthy)`.

### Services and Ports

| Service | URL | Credentials |
|---|---|---|
| Operate (process monitor) | http://localhost:8081 | `demo / demo` |
| Tasklist (human tasks) | http://localhost:8082 | `demo / demo` |
| Connectors | http://localhost:8085 | — |
| Zeebe REST API | http://localhost:8088 | — |
| Zeebe gRPC | `localhost:26500` | — |
| Elasticsearch | http://localhost:9200 | — |

---

## 4. Python Client Setup

```powershell
mkdir C:\camunda8\python-client
cd C:\camunda8\python-client

# Create virtual environment (using uv)
uv venv bpm
bpm\Scripts\activate

# Install pyzeebe
uv pip install pyzeebe
```

Or with pip:

```powershell
python -m venv bpm
bpm\Scripts\activate
pip install pyzeebe
```

### pyzeebe compatibility

| pyzeebe version | Camunda / Zeebe version |
|---|---|
| 4.7.x | 8.5, 8.6, 8.7, 8.8 |

---

## 5. Stopping Camunda

```powershell
cd C:\camunda8
# Stop but keep data
docker compose -f docker-compose-core.yaml stop

# Stop and remove all containers + volumes (resets all data)
docker compose -f docker-compose-core.yaml down -v
```

---

## References

- [Camunda 8 Docs — Docker Compose](https://docs.camunda.io/docs/self-managed/setup/deploy/local/docker-compose/)
- [camunda-distributions releases](https://github.com/camunda/camunda-distributions/releases)
- [pyzeebe documentation](https://camunda-community-hub.github.io/pyzeebe/)
- [Camunda Desktop Modeler download](https://camunda.com/download/modeler/)


