"""
Asset Administration Shell (AAS) module for NEXUS.

Builds AAS shells for all three PPR dimensions from existing data models:
  - WireHarnessAAS   (Product)   — from CDM WireHarness
  - AssemblyStationAAS (Resource) — from simulation StationConfig
  - BillOfProcessAAS  (Process)  — from ProductionBillOfProcess
  - ComponentAAS      (Tier-2)   — from CDM component definitions

Conforms to IDTA AAS v3 with real IDTA semantic IRIs.
Uses basyx-python-sdk for serialization.
"""
