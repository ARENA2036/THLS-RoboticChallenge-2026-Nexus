"""
AssemblyBoardLayoutAAS — Layout AAS for a board peg/holder configuration.

Carries two submodels:
  1. DigitalNameplate          (IDTA 02006-2-0)
  2. AssemblyBoardLayout       (urn:NEXUS:submodel:AssemblyBoardLayout:1-0)

GlobalAssetId convention:
    urn:NEXUS:layout:{harness_id}
"""

from dataclasses import dataclass

import basyx.aas.model as model

from ..submodels.digital_nameplate import build_digital_nameplate
from ..submodels.assembly_board_layout import build_assembly_board_layout


@dataclass
class AssemblyBoardLayoutAASBundle:
    """A complete AssemblyBoardLayoutAAS: shell + its submodels."""
    shell: model.AssetAdministrationShell
    nameplate_submodel: model.Submodel
    layout_submodel: model.Submodel

    def all_objects(self) -> list:
        return [self.shell, self.nameplate_submodel, self.layout_submodel]


def build_assembly_board_layout_aas(
    harness_id: str,
    layout_response,
    board_config=None,
    harness_part_number: str = "",
    manufacturer_name: str = "NEXUS",
) -> AssemblyBoardLayoutAASBundle:
    """Build a complete AssemblyBoardLayoutAAS from a LayoutResponse.

    Args:
        harness_id: Harness ID (used in GlobalAssetId and to link to WireHarnessAAS).
        layout_response: LayoutResponse from LayoutGeneratorService.generate_layout().
        board_config: Optional LayoutModels.BoardConfig for board dimensions.
        harness_part_number: Optional harness part number for the nameplate.
        manufacturer_name: Organisation that generated the layout.

    Returns:
        AssemblyBoardLayoutAASBundle with shell and two submodels.
    """
    safe_id = harness_id.replace(" ", "_").replace("/", "_")
    global_asset_id = f"urn:NEXUS:layout:{safe_id}"
    nameplate_id = f"{global_asset_id}/submodel/DigitalNameplate"
    layout_id = f"{global_asset_id}/submodel/AssemblyBoardLayout"

    pegs = len(layout_response.pegs)
    holders = len(layout_response.connector_holders)

    nameplate = build_digital_nameplate(
        nameplate_id,
        manufacturer_name=manufacturer_name,
        manufacturer_part_number=harness_part_number or harness_id,
        manufacturer_product_designation=(
            f"Assembly board layout for harness {harness_id}: "
            f"{pegs} pegs, {holders} connector holders"
        ),
        manufacturer_product_family="AssemblyBoardLayout",
        manufacturer_product_type="PegHolderLayout",
    )

    layout_sm = build_assembly_board_layout(
        layout_id,
        layout_response,
        board_config=board_config,
        harness_id=harness_id,
    )

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
        submodel={_sm_ref(nameplate), _sm_ref(layout_sm)},
    )

    return AssemblyBoardLayoutAASBundle(
        shell=shell,
        nameplate_submodel=nameplate,
        layout_submodel=layout_sm,
    )
