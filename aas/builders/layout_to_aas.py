"""
Builder: LayoutResponse → AssemblyBoardLayoutAAS.
"""

from ..shells.assembly_board_layout_aas import (
    AssemblyBoardLayoutAASBundle,
    build_assembly_board_layout_aas,
)


def build_aas_from_layout(
    harness_id: str,
    layout_response,
    board_config=None,
    harness_part_number: str = "",
    manufacturer_name: str = "NEXUS",
) -> AssemblyBoardLayoutAASBundle:
    """Build an AssemblyBoardLayoutAAS from a LayoutResponse.

    Args:
        harness_id: Harness ID linking this layout to its WireHarnessAAS.
        layout_response: LayoutResponse from LayoutGeneratorService.generate_layout().
        board_config: Optional LayoutModels.BoardConfig for board dimensions.
        harness_part_number: Optional harness part number for the nameplate.
        manufacturer_name: Organisation that generated the layout.

    Returns:
        AssemblyBoardLayoutAASBundle (shell + 2 submodels).
    """
    return build_assembly_board_layout_aas(
        harness_id,
        layout_response,
        board_config=board_config,
        harness_part_number=harness_part_number,
        manufacturer_name=manufacturer_name,
    )
