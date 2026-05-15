"""
BillOfProcessAAS — Process AAS for a ProductionBillOfProcess.

Carries two submodels:
  1. DigitalNameplate    (IDTA 02006-2-0)
  2. ProcessParametersType (IDTA 02031-1-0)

GlobalAssetId convention:
    urn:NEXUS:bop:{production_id}
"""

from dataclasses import dataclass

import basyx.aas.model as model

from ..submodels.digital_nameplate import build_digital_nameplate
from ..submodels.process_parameters import build_process_parameters


@dataclass
class BillOfProcessAASBundle:
    """A complete BillOfProcessAAS: shell + its submodels."""
    shell: model.AssetAdministrationShell
    nameplate_submodel: model.Submodel
    process_parameters_submodel: model.Submodel

    def all_objects(self) -> list:
        return [
            self.shell,
            self.nameplate_submodel,
            self.process_parameters_submodel,
        ]


def build_bill_of_process_aas(
    bill_of_process,
    manufacturer_name: str = "NEXUS",
) -> BillOfProcessAASBundle:
    """Build a complete BillOfProcessAAS from a ProductionBillOfProcess.

    Args:
        bill_of_process: ProductionBillOfProcess instance from bill_of_process/BoPModels.py.
        manufacturer_name: Organisation that generated the BoP.

    Returns:
        BillOfProcessAASBundle with shell and two submodels.
    """
    safe_pid = bill_of_process.production_id.replace(" ", "_").replace("/", "_")
    global_asset_id = f"urn:NEXUS:bop:{safe_pid}"
    nameplate_id = f"{global_asset_id}/submodel/DigitalNameplate"
    process_params_id = f"{global_asset_id}/submodel/ProcessParametersType"

    # --- DigitalNameplate ---
    nameplate = build_digital_nameplate(
        nameplate_id,
        manufacturer_name=manufacturer_name,
        manufacturer_part_number=bill_of_process.production_id,
        manufacturer_product_designation=(
            f"Bill of Process for production batch {bill_of_process.production_id}"
        ),
        manufacturer_product_family="ProductionBillOfProcess",
        manufacturer_product_type="WireHarnessAssemblyPlan",
        date_of_manufacture=bill_of_process.created_at.strftime("%Y-%m-%d"),
    )

    # --- ProcessParametersType ---
    process_params = build_process_parameters(process_params_id, bill_of_process)

    # --- Shell ---
    asset_info = model.AssetInformation(
        model.AssetKind.INSTANCE,
        global_asset_id=global_asset_id,
    )

    def _sm_ref(sm: model.Submodel) -> model.ModelReference:
        return model.ModelReference(
            (model.Key(model.KeyTypes.SUBMODEL, sm.id),),
            model.Submodel,
        )

    shell = model.AssetAdministrationShell(
        asset_information=asset_info,
        id_=f"{global_asset_id}/shell",
        submodel={_sm_ref(nameplate), _sm_ref(process_params)},
    )

    return BillOfProcessAASBundle(
        shell=shell,
        nameplate_submodel=nameplate,
        process_parameters_submodel=process_params,
    )
