"""
BoP → AAS builder.

Converts a ProductionBillOfProcess into a BillOfProcessAAS.

Usage:
    from aas.builders.bop_to_aas import build_aas_from_bop
    bundle = build_aas_from_bop(bill_of_process)
"""

import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from ..shells.bill_of_process_aas import (
    build_bill_of_process_aas,
    BillOfProcessAASBundle,
)


def build_aas_from_bop(
    bill_of_process,
    manufacturer_name: str = "NEXUS",
) -> BillOfProcessAASBundle:
    """Build a BillOfProcessAAS from a ProductionBillOfProcess.

    Args:
        bill_of_process: ProductionBillOfProcess from bill_of_process/BoPModels.py.
        manufacturer_name: Organisation that generated the BoP.

    Returns:
        BillOfProcessAASBundle with shell and two submodels.
    """
    return build_bill_of_process_aas(
        bill_of_process,
        manufacturer_name=manufacturer_name,
    )
