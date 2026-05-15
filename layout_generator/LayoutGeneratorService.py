"""
Layout Generator Service - Main orchestration logic.
"""


from .algorithms.ConnectorPlacementEngine import ConnectorPlacementEngine
from .algorithms.LayoutOptimizer import LayoutOptimizer
from .algorithms.PegPlacementEngine import PegPlacementEngine
from .LayoutModels import (
    BoardConfig,
    ConnectorHolderPosition,
    LayoutMetrics,
    LayoutRequest,
    LayoutResponse,
    PegPlacementReason,
    PegPosition,
)


class LayoutGeneratorService:
    """
    Main service class for generating board layouts.

    Orchestrates the layout generation pipeline:
    1. Validate CDM
    2. Place connector holders
    3. Place pegs
    4. Optimize layout
    """

    def generate_layout(self, request: LayoutRequest) -> LayoutResponse:
        """
        Generate a complete board layout from the request.

        Args:
            request: LayoutRequest containing harness, board_config, and parameters

        Returns:
            LayoutResponse with connector holders, pegs, and metrics
        """
        harness = request.harness
        board_config = request.board_config
        parameters = request.parameters

        # Step 1: Place connector holders
        connector_engine = ConnectorPlacementEngine(
            harness,
            board_config,
            parameters
        )
        connector_holders = connector_engine.place_connectors()

        # Step 2: Place pegs
        peg_engine = PegPlacementEngine(
            harness,
            board_config,
            parameters
        )
        raw_pegs = peg_engine.place_pegs()

        # Step 3: Optimize layout
        optimizer = LayoutOptimizer(board_config, parameters)
        optimized_holders, optimized_pegs = optimizer.optimize(
            connector_holders,
            raw_pegs
        )

        # Step 4: Compute metrics
        metrics = self._compute_metrics(
            optimized_holders,
            optimized_pegs,
            board_config,
            optimizer.merged_count,
            optimizer.shifted_count,
            peg_engine.intersection_offset_applied_count,
            peg_engine.intersection_offset_fallback_count,
            peg_engine.intersection_offset_clamped_count,
        )

        return LayoutResponse(
            connector_holders=optimized_holders,
            pegs=optimized_pegs,
            metrics=metrics,
        )


    def _compute_metrics(
        self,
        holders: list[ConnectorHolderPosition],
        pegs: list[PegPosition],
        board_config: BoardConfig,
        merged_count: int,
        shifted_count: int,
        intersection_offset_applied_count: int,
        intersection_offset_fallback_count: int,
        intersection_offset_clamped_count: int,
    ) -> LayoutMetrics:
        """Compute layout metrics."""
        # Count pegs by reason
        breakout_count = sum(1 for p in pegs if p.reason == PegPlacementReason.BREAKOUT_POINT)
        interval_count = sum(1 for p in pegs if p.reason == PegPlacementReason.INTERVAL)

        # Calculate board utilization (simplified: based on bounding box of elements)
        if holders or pegs:
            all_points = []
            for holder in holders:
                all_points.append((holder.position.x, holder.position.y))
            for peg in pegs:
                all_points.append((peg.position.x, peg.position.y))

            min_x = min(p[0] for p in all_points)
            max_x = max(p[0] for p in all_points)
            min_y = min(p[1] for p in all_points)
            max_y = max(p[1] for p in all_points)

            used_area = (max_x - min_x) * (max_y - min_y)
            total_area = board_config.width_mm * board_config.height_mm
            utilization = (used_area / total_area * 100) if total_area > 0 else 0
        else:
            utilization = 0

        return LayoutMetrics(
            total_pegs=len(pegs),
            total_holders=len(holders),
            merged_positions=merged_count,
            shifted_positions=shifted_count,
            board_utilization_percent=round(utilization, 2),
            breakout_pegs=breakout_count,
            interval_pegs=interval_count,
            intersection_offset_applied_count=intersection_offset_applied_count,
            intersection_offset_fallback_count=intersection_offset_fallback_count,
            intersection_offset_clamped_count=intersection_offset_clamped_count,
        )
