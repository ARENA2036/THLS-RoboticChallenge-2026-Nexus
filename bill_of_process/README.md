# 📝 Bill of Process (BoP) Derivation

The **Bill of Process (BoP)** module implements **Step 3: BoP Derivation** of the robotic assembly pipeline. It transforms the [Canonical Description Model (CDM)](../cdm) and the [Board Layout](../layout_generator) into a sequenced, fully parameterized assembly plan.

## 🌟 Overview

This module addresses **Gap 1: Manual Knowledge Extraction and Process Planning** by automatically generating machine-executable instructions. It populates the **Process (P)** dimension of the Product-Process-Resource (PPR) model, following the **Capability-Skill-Service (CSS)** methodology.

The BoP is organized into five sequential phases:

1.  **Board Setup**: Placement of all pegs and connector holders at the positions and orientations defined in the resource model. Steps are ordered to minimize arm travel.
2.  **Wire Routing and Connector Insertion**: Retrieval of pre-crimped wires and routing through the ordered sequence of peg positions. Routing follows an **inside-out layering strategy** (inner-cavity wires and trunk segments are processed before outer ones).
3.  **Protection and Fixing**: Application of protection materials (shrink tubing, corrugated conduit) and mechanical fixings (cable ties, clips).
4.  **Connector Assembly**: (Future expansion) Secondary assembly tasks on connector housings.
5.  **Finalization**: Removal of the completed wire harness from the assembly board.

## 🏗️ Components

- **BoPGeneratorService**: The main orchestration logic that assembles phases and steps.
- **WireRoutingOrderEngine**: Implements the logic for ordering wire routing to ensure accessibility and prevent tangling (inside-out strategy).
- **BoPModels**: Pydantic models defining the structure of phases, steps, and parameters.

## 🚀 Usage

The BoP is the final output of the planning pipeline. It is serialized as a **BillOfProcessAAS** [Asset Administration Shell](../aas), which can be dispatched to robotic workcells via OPC UA.

```python
from bill_of_process.BoPGeneratorService import BoPGeneratorService
from bill_of_process.BoPConfig import BoPGeneratorConfig, HarnessInput

# Initialize service
service = BoPGeneratorService()

# Configure inputs (CDM + Layout)
config = BoPGeneratorConfig(
    production_id="PROD_001",
    harness_inputs=[
        HarnessInput(
            harness=my_cdm_harness,
            layout_response=my_layout_response,
            station_id="STATION_A"
        )
    ]
)

# Generate the BoP
bop = service.generate(config)

# bop.phases contains the sequenced steps
```

---
> [!NOTE]
> Each atomic process step is self-contained, carrying its process type, typed parameters, assigned resources, and dependency relationships. See Section IV-C of the [ETFA 2026 Paper](../ETFA_2026__From_Design_to_Action__Enabling_End_to_End_Robotic_Wire_Harness_Assembly.pdf) for further details.
