# Design Document — Store Intelligence

> **Phase 0 skeleton.** Content will be expanded during implementation (minimum 250 words required for submission).

## 1. System Overview

<!-- Describe the end-to-end flow: CCTV → Detection Pipeline → Event Stream → Intelligence API → Dashboard -->

## 2. Architecture Diagram

<!-- Insert or describe component diagram -->

## 3. Component Breakdown

### 3.1 Detection Pipeline (`pipeline/`)

<!-- YOLO detection, tracking, zone mapping, event emission -->

### 3.2 Intelligence API (`app/`)

<!-- FastAPI endpoints, ingestion, metrics, funnel, anomalies -->

### 3.3 Data Layer

<!-- SQLite file database (store_intelligence.db), SQLAlchemy ORM, session model -->

### 3.4 Dashboard (`dashboard/`)

<!-- Streamlit real-time metrics display -->

## 4. Event Schema

<!-- Reference the required JSON event schema -->

## 5. Data Flow

<!-- Clip processing → JSONL events → ingest → query endpoints -->

## 6. AI-Assisted Decisions

<!-- Document 2–3 instances where an LLM influenced design choices -->

## 7. Deployment

<!-- docker-compose topology, environment variables -->

## 8. Testing Strategy

<!-- pytest coverage targets, edge case scenarios -->
