# 🔍 Extraction Engine

The **Extraction Engine** implements **Step 1: Ingestion and Semantic Enrichment** of the NEXUS robotic assembly pipeline. It transforms fragmented, heterogeneous design data—including KBL, VEC, STP files, and PDFs—into the structured [Canonical Description Model (CDM)](../cdm).

By leveraging Vision-Language Models (VLMs) and traditional parsers, it ensures that the manufacturing blueprint is accurate and enriched with all necessary product data.

## 🌟 Overview

As detailed in Section IV-A of the [ETFA 2026 Paper](../ETFA_2026__From_Design_to_Action__Enabling_End_to_End_Robotic_Wire_Harness_Assembly.pdf), this module bridges the "engineering-to-execution" gap by inferring manufacturing intent from diverse design artifacts.

### Key Features:
- **Baseline Parsing**: High-fidelity ingestion of industry-standard KBL and XML files.
- **AI-Driven Visual Enrichment**: Employs a Vision-Language Model (VLM) for multimodal fusion, extracting geometric structures and part information from PDFs and technical drawings via OCR.
- **Component Enrichment**: Integrates with external databases (e.g., DigiKey) to retrieve precise mechanical properties and part specifications.
- **SSE-Powered Pipeline**: Provides real-time progress updates through Server-Sent Events (SSE) during multi-step extraction runs.
- **Automated Archiving**: Every extraction run is timestamped and archived, preserving input files and generated models for traceability.

## 🏗️ Extraction Pipeline

The engine executes a three-step enrichment process:

1.  **KBL Parsing**: Establishes the logical baseline (topological skeleton) from structured design data.
2.  **External Enrichment**: Fetches mechanical bounding boxes, mating directions, and crimp parameters from component databases.
3.  **Multimodal Fusion**: Processes technical drawings alongside the baseline model to resolve geometric ambiguities and associate visual annotations with specific harness nodes.

## 📁 Project Structure

- `main.py`: FastAPI entry point and pipeline orchestration.
- `parsing/`: Logic for importing KBL, VEC, and processing visual schemas.
- `quoting/`: Interface for external component enrichment (DigiKey).
- `validation/`: Schema enforcement and data integrity checks.

## 🚀 Getting Started

### Prerequisites
- Python 3.13+
- Access to the VLM (Qwen-3.6 or equivalent) for visual enrichment.

### Installation

```bash
# Install dependencies
pip install -r extraction/requirements.txt
```

### Running the Service

```bash
# Start the FastAPI server
uvicorn extraction.main:app --reload
```
The service runs on `http://127.0.0.1:8000` by default.

---
> [!NOTE]
> The Extraction Engine is designed to work in tandem with a human-in-the-loop refinement process for complex topologies. See Section VII of the [ETFA 2026 Paper](../ETFA_2026__From_Design_to_Action__Enabling_End_to_End_Robotic_Wire_Harness_Assembly.pdf).
