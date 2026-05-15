"""
Board Layout Visualizer - Main rendering logic.

Renders a comprehensive 2D view of wire harness board layouts including:
- Board background with grid
- Forbidden zones (hatched areas)
- Individual wire paths (offset parallel lines)
- Topology nodes (branch points)
- Pegs (color-coded by placement reason)
- Connector holders with mating direction arrows
"""

import math

import matplotlib.patches as patches
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from ..LayoutModels import (
    BoardConfig,
    Connection,
    ConnectorHolderPosition,
    ConnectorOccurrence,
    ForbiddenZone,
    LayoutResponse,
    Node,
    PegPosition,
    Segment,
    WireHarness,
    WireOccurrence,
)
from .VisualizerStyle import DEFAULT_STYLE, VisualizerStyle

# Wire color mapping from color codes to hex values
WIRE_COLOR_MAP: dict[str, str] = {
    "RD": "#EF4444",
    "RED": "#EF4444",
    "BK": "#171717",
    "BLACK": "#171717",
    "BU": "#3B82F6",
    "BLUE": "#3B82F6",
    "GN": "#22C55E",
    "GREEN": "#22C55E",
    "YE": "#EAB308",
    "YELLOW": "#EAB308",
    "WH": "#E5E5E5",
    "WHITE": "#E5E5E5",
    "OG": "#F97316",
    "ORANGE": "#F97316",
    "VT": "#A855F7",
    "PURPLE": "#A855F7",
    "BR": "#78350F",
    "BROWN": "#78350F",
    "GY": "#6B7280",
    "GREY": "#6B7280",
    "GRAY": "#6B7280",
    "PK": "#EC4899",
    "PINK": "#EC4899",
}


class BoardLayoutVisualizer:
    """
    Visualizes the wire harness board layout.

    Renders three layers:
    1. Board background with grid and forbidden zones
    2. Cable segments and nodes from the CDM
    3. Connector holders and pegs from the layout response
    """

    def __init__(
        self,
        board_config: BoardConfig,
        style: VisualizerStyle | None = None,
    ):
        self.board_config = board_config
        self.style = style or DEFAULT_STYLE

        self.harness: WireHarness | None = None
        self.layout: LayoutResponse | None = None

        self._figure: Figure | None = None
        self._axes: Axes | None = None

    def add_harness(self, harness: WireHarness) -> None:
        """Add wire harness CDM for visualization."""
        self.harness = harness

    def add_layout(self, layout: LayoutResponse) -> None:
        """Add layout response for visualization."""
        self.layout = layout

    def render(
        self,
        show_grid: bool = True,
        show_forbidden_zones: bool = True,
        show_labels: bool = True,
        show_buffer_zones: bool = True,
        show_individual_wires: bool = True,
        show_legend: bool = True,
        figsize: tuple[float, float] | None = None,
    ) -> Figure:
        """
        Render the complete board layout.

        Args:
            show_grid: Whether to show the grid overlay
            show_forbidden_zones: Whether to show forbidden zones
            show_labels: Whether to show element labels
            show_buffer_zones: Whether to show connector buffer zones
            show_individual_wires: Whether to show individual wire paths
            figsize: Figure size in inches (width, height)

        Returns:
            matplotlib Figure object
        """
        # Calculate figure size based on board dimensions
        if figsize is None:
            aspect_ratio = self.board_config.width_mm / self.board_config.height_mm
            base_height = 8.0
            figsize = (base_height * aspect_ratio, base_height)

        self._figure, self._axes = plt.subplots(figsize=figsize)

        # Set up axes
        self._axes.set_xlim(0, self.board_config.width_mm)
        self._axes.set_ylim(0, self.board_config.height_mm)
        self._axes.set_aspect("equal")
        self._axes.set_xlabel("X (mm)")
        self._axes.set_ylabel("Y (mm)")
        self._axes.set_title("Wire Harness Board Layout")

        # Layer 1: Board background
        self._draw_board_background()

        if show_grid:
            self._draw_grid()

        if show_forbidden_zones:
            self._draw_forbidden_zones()

        # Layer 2: Cable segments and nodes
        if self.harness:
            if show_individual_wires:
                self._draw_individual_wires()
            else:
                self._draw_segments()
            self._draw_nodes()

        # Layer 3: Connector holders and pegs
        if self.layout:
            if show_buffer_zones:
                self._draw_buffer_zones()
            self._draw_connector_pigtails()  # Draw lines from nodes to offset connectors
            self._draw_connector_holders(show_labels)
            self._draw_pegs(show_labels)

        # Layer 4: Connectors from CDM (if no layout response)
        if self.harness and not self.layout:
            self._draw_cdm_connectors(show_labels)

        # Add legend
        if show_legend:
            self._add_legend()

        plt.tight_layout()

        return self._figure

    def _draw_board_background(self) -> None:
        """Draw the board background."""
        board_rect = patches.Rectangle(
            (0, 0),
            self.board_config.width_mm,
            self.board_config.height_mm,
            linewidth=self.style.board_border_width,
            edgecolor=self.style.board_border_color,
            facecolor=self.style.board_background_color,
            zorder=0,
        )
        self._axes.add_patch(board_rect)

    def _draw_grid(self) -> None:
        """Draw the grid overlay."""
        # Vertical lines
        for x_position in np.arange(0, self.board_config.width_mm + 1, self.style.grid_spacing_mm):
            self._axes.axvline(
                x=x_position,
                color=self.style.grid_color,
                linewidth=self.style.grid_line_width,
                zorder=1,
            )

        # Horizontal lines
        for y_position in np.arange(0, self.board_config.height_mm + 1, self.style.grid_spacing_mm):
            self._axes.axhline(
                y=y_position,
                color=self.style.grid_color,
                linewidth=self.style.grid_line_width,
                zorder=1,
            )

    def _draw_forbidden_zones(self) -> None:
        """Draw forbidden zones."""
        for zone in self.board_config.forbidden_zones:
            self._draw_single_forbidden_zone(zone)

    def _draw_single_forbidden_zone(self, zone: ForbiddenZone) -> None:
        """Draw a single forbidden zone."""
        if len(zone.vertices) < 3:
            return

        polygon_vertices = [(vertex.x, vertex.y) for vertex in zone.vertices]
        polygon = patches.Polygon(
            polygon_vertices,
            closed=True,
            facecolor=self.style.forbidden_zone_color,
            alpha=self.style.forbidden_zone_alpha,
            edgecolor=self.style.forbidden_zone_edge_color,
            linewidth=self.style.forbidden_zone_edge_width,
            zorder=2,
        )
        self._axes.add_patch(polygon)

    def _draw_segments(self) -> None:
        """Draw cable segments (simple line mode, no individual wires)."""
        if not self.harness:
            return

        for segment in self.harness.segments:
            # In new CDM, segments have embedded Node objects
            start_node = segment.start_node
            end_node = segment.end_node

            # Use default line width for segments
            line_width = self.style.segment_line_width

            # Apply board offset
            start_x = start_node.position.coord_x + self.board_config.offset_x
            start_y = start_node.position.coord_y + self.board_config.offset_y
            end_x = end_node.position.coord_x + self.board_config.offset_x
            end_y = end_node.position.coord_y + self.board_config.offset_y

            self._axes.plot(
                [start_x, end_x],
                [start_y, end_y],
                color=self.style.segment_color,
                linewidth=line_width,
                solid_capstyle="round",
                zorder=3,
            )

    def _get_wire_color(self, wire_occurrence: WireOccurrence) -> str:
        """Get the color for a wire occurrence based on its definition."""
        if not wire_occurrence or not wire_occurrence.wire:
            return "#999999"

        wire_def = wire_occurrence.wire

        # Try to get color from cover_colors
        if wire_def.cover_colors:
            # Get base color
            for color_spec in wire_def.cover_colors:
                if "base" in color_spec.color_type.lower():
                    color_code = color_spec.color_code.upper()
                    return WIRE_COLOR_MAP.get(color_code, "#999999")
            # Fallback to first color
            color_code = wire_def.cover_colors[0].color_code.upper()
            return WIRE_COLOR_MAP.get(color_code, "#999999")

        return "#999999"

    def _get_wire_occurrence_color(self, wire_occ_id: str) -> str:
        """Get color by wire occurrence ID."""
        if not self.harness:
            return "#999999"

        for wire_occ in self.harness.wire_occurrences:
            if wire_occ.id == wire_occ_id:
                return self._get_wire_color(wire_occ)

        return "#999999"

    def _get_connections_for_segment(self, segment: Segment) -> list[Connection]:
        """Get all connections that route through a segment."""
        if not self.harness:
            return []

        connections = []
        for connection in self.harness.connections:
            # In new CDM, connection.segments is a list of Segment objects
            for conn_segment in connection.segments:
                if conn_segment.id == segment.id:
                    connections.append(connection)
                    break

        return connections

    def _draw_individual_wires(self) -> None:
        """Draw individual wire paths as offset parallel lines within bundles."""
        if not self.harness:
            return

        for segment in self.harness.segments:
            # In new CDM, segments have embedded Node objects
            start_node = segment.start_node
            end_node = segment.end_node

            # Apply board offset
            start_x = start_node.position.coord_x + self.board_config.offset_x
            start_y = start_node.position.coord_y + self.board_config.offset_y
            end_x = end_node.position.coord_x + self.board_config.offset_x
            end_y = end_node.position.coord_y + self.board_config.offset_y

            # Get connections through this segment
            segment_connections = self._get_connections_for_segment(segment)
            wire_count = len(segment_connections)

            if wire_count == 0:
                # Draw empty segment as thin dashed line
                self._axes.plot(
                    [start_x, end_x],
                    [start_y, end_y],
                    color="#E5E7EB",
                    linewidth=2,
                    linestyle="--",
                    zorder=3,
                )
                continue

            # Calculate perpendicular offset vector
            segment_dx = end_x - start_x
            segment_dy = end_y - start_y
            segment_length = math.sqrt(segment_dx ** 2 + segment_dy ** 2)

            if segment_length == 0:
                continue

            # Normal vector (perpendicular to segment)
            normal_x = -segment_dy / segment_length
            normal_y = segment_dx / segment_length

            # Wire spacing settings
            wire_spacing = 3.0  # mm between wire centers
            total_bundle_width = (wire_count - 1) * wire_spacing
            start_offset = -total_bundle_width / 2

            # Draw each wire with offset
            for wire_index, connection in enumerate(segment_connections):
                # Get wire color from wire_occurrence
                wire_color = "#999999"
                if connection.wire_occurrence:
                    wire_color = self._get_wire_color(connection.wire_occurrence)

                wire_offset = start_offset + wire_index * wire_spacing

                # Calculate offset positions
                offset_x = normal_x * wire_offset
                offset_y = normal_y * wire_offset

                wire_start_x = start_x + offset_x
                wire_start_y = start_y + offset_y
                wire_end_x = end_x + offset_x
                wire_end_y = end_y + offset_y

                # Draw the wire
                self._axes.plot(
                    [wire_start_x, wire_end_x],
                    [wire_start_y, wire_end_y],
                    color=wire_color,
                    linewidth=1.5,
                    solid_capstyle="round",
                    zorder=4,
                )

    def _draw_cdm_connectors(self, show_labels: bool) -> None:
        """Draw connectors from CDM when no layout response is available."""
        if not self.harness:
            return

        node_map: dict[str, Node] = {node.id: node for node in self.harness.nodes}

        for connector_occ in self.harness.connector_occurrences:
            # Get position from node_id or direct position
            position_x = 0.0
            position_y = 0.0

            if connector_occ.node_id:
                node = node_map.get(connector_occ.node_id)
                if node:
                    position_x = node.position.coord_x + self.board_config.offset_x
                    position_y = node.position.coord_y + self.board_config.offset_y
            elif connector_occ.position:
                position_x = connector_occ.position.coord_x + self.board_config.offset_x
                position_y = connector_occ.position.coord_y + self.board_config.offset_y
            else:
                continue

            # Use physical dimensions from connector occurrence
            width = connector_occ.physical_width
            height = connector_occ.physical_height

            half_width = width / 2
            half_height = height / 2

            # Draw connector rectangle
            rect = patches.Rectangle(
                (position_x - half_width, position_y - half_height),
                width,
                height,
                linewidth=self.style.connector_edge_width,
                edgecolor=self.style.connector_edge_color,
                facecolor=self.style.connector_color,
                alpha=self.style.connector_alpha,
                zorder=6,
            )
            self._axes.add_patch(rect)

            # Draw cavities inside connector
            self._draw_connector_cavities(connector_occ, position_x, position_y, width, height)

            if show_labels:
                # Connector ID label
                self._axes.annotate(
                    connector_occ.id,
                    (position_x, position_y + half_height + 5),
                    fontsize=self.style.connector_label_font_size,
                    color=self.style.connector_label_color,
                    ha="center",
                    va="bottom",
                    fontweight="bold",
                    zorder=8,
                )
                # Connector part number (smaller, below ID)
                if connector_occ.connector:
                    self._axes.annotate(
                        connector_occ.connector.part_number,
                        (position_x, position_y + half_height + 18),
                        fontsize=self.style.connector_label_font_size - 1,
                        color="#666666",
                        ha="center",
                        va="bottom",
                        zorder=8,
                    )

    def _draw_connector_cavities(
        self,
        connector_occ: ConnectorOccurrence,
        center_x: float,
        center_y: float,
        width: float,
        height: float,
    ) -> None:
        """Draw individual cavities inside a connector."""
        if not self.harness:
            return

        cavity_count = len(connector_occ.contact_points)
        if cavity_count == 0:
            return

        # Calculate cavity grid layout
        columns = 4 if cavity_count > 6 else (2 if cavity_count > 2 else 1)
        rows = math.ceil(cavity_count / columns)

        cavity_spacing_x = width / (columns + 1)
        cavity_spacing_y = height / (rows + 1)
        cavity_radius = 3.0

        for cavity_index, contact_point in enumerate(connector_occ.contact_points):
            row = cavity_index // columns
            col = cavity_index % columns

            cavity_x = center_x - width / 2 + (col + 1) * cavity_spacing_x
            cavity_y = center_y - height / 2 + (row + 1) * cavity_spacing_y

            # Find if this contact point has a wire connected
            wire_color = "#DDDDDD"  # Empty cavity color

            for connection in self.harness.connections:
                for extremity in connection.extremities:
                    if extremity.contact_point.id == contact_point.id:
                        if connection.wire_occurrence:
                            wire_color = self._get_wire_color(connection.wire_occurrence)
                        break

            # Draw cavity circle
            cavity_circle = patches.Circle(
                (cavity_x, cavity_y),
                cavity_radius,
                facecolor=wire_color,
                edgecolor="#555555",
                linewidth=0.5,
                zorder=7,
            )
            self._axes.add_patch(cavity_circle)

    def _draw_nodes(self) -> None:
        """Draw topology nodes."""
        if not self.harness:
            return

        node_x_positions = [
            node.position.coord_x + self.board_config.offset_x
            for node in self.harness.nodes
        ]
        node_y_positions = [
            node.position.coord_y + self.board_config.offset_y
            for node in self.harness.nodes
        ]

        self._axes.scatter(
            node_x_positions,
            node_y_positions,
            c=self.style.node_color,
            marker=self.style.node_marker,
            s=self.style.node_size,
            zorder=4,
            label="Nodes",
        )

    def _draw_buffer_zones(self) -> None:
        """Draw connector buffer zones."""
        if not self.layout:
            return

        for holder in self.layout.connector_holders:
            circle = patches.Circle(
                (holder.position.x, holder.position.y),
                holder.buffer_radius_mm,
                facecolor=self.style.buffer_zone_color,
                alpha=self.style.buffer_zone_alpha,
                edgecolor=self.style.buffer_zone_color,
                linestyle=self.style.buffer_zone_line_style,
                linewidth=self.style.buffer_zone_line_width,
                zorder=5,
            )
            self._axes.add_patch(circle)

    def _draw_connector_pigtails(self) -> None:
        """Draw pigtail lines from nodes to their offset connector positions."""
        if not self.layout or not self.harness:
            return

        # Build connector-to-node mapping from connector occurrences
        connector_node_map = {
            conn_occ.id: conn_occ.node_id
            for conn_occ in self.harness.connector_occurrences
            if conn_occ.node_id
        }
        node_map = {node.id: node for node in self.harness.nodes}

        for holder in self.layout.connector_holders:
            node_id = connector_node_map.get(holder.connector_id)
            if not node_id:
                continue

            node = node_map.get(node_id)
            if not node:
                continue

            # Node position (with board offset)
            node_x = node.position.coord_x + self.board_config.offset_x
            node_y = node.position.coord_y + self.board_config.offset_y

            # Connector holder position
            holder_x = holder.position.x
            holder_y = holder.position.y

            # Draw pigtail line from node to connector
            self._axes.plot(
                [node_x, holder_x],
                [node_y, holder_y],
                color=self.style.segment_color,
                linewidth=2.0,
                solid_capstyle="round",
                zorder=3,
            )

    def _draw_connector_holders(self, show_labels: bool) -> None:
        """Draw connector holders."""
        if not self.layout:
            return

        for holder in self.layout.connector_holders:
            self._draw_single_connector(holder, show_labels)

    def _draw_single_connector(
        self,
        holder: ConnectorHolderPosition,
        show_labels: bool
    ) -> None:
        """Draw a single connector holder."""
        # Calculate rectangle corners (centered on position)
        half_width = holder.width_mm / 2
        half_height = holder.height_mm / 2

        # Create rotated rectangle using transform for proper center rotation
        angle_rad = math.radians(holder.orientation_deg)

        import matplotlib.transforms as transforms

        # Create a transform that rotates around origin then translates
        transform = (
            transforms.Affine2D()
            .rotate(angle_rad)
            .translate(holder.position.x, holder.position.y)
            + self._axes.transData
        )

        # Rectangle centered at origin (will be transformed)
        rect = patches.Rectangle(
            (-half_width, -half_height),
            holder.width_mm,
            holder.height_mm,
            linewidth=self.style.connector_edge_width,
            edgecolor=self.style.connector_edge_color,
            facecolor=self.style.connector_color,
            alpha=self.style.connector_alpha,
            zorder=6,
            transform=transform,
        )
        self._axes.add_patch(rect)

        # Draw mating direction arrow
        arrow_length = max(holder.width_mm, holder.height_mm) * 0.6
        arrow_dx = arrow_length * math.cos(angle_rad)
        arrow_dy = arrow_length * math.sin(angle_rad)

        self._axes.arrow(
            holder.position.x,
            holder.position.y,
            arrow_dx,
            arrow_dy,
            head_width=self.style.arrow_head_width,
            head_length=self.style.arrow_head_length,
            fc=self.style.arrow_color,
            ec=self.style.arrow_color,
            linewidth=self.style.arrow_width,
            zorder=7,
        )

        if show_labels:
            self._axes.annotate(
                holder.connector_id,
                (holder.position.x, holder.position.y + half_height + 5),
                fontsize=self.style.connector_label_font_size,
                color=self.style.connector_label_color,
                ha="center",
                va="bottom",
                zorder=8,
            )

    def _draw_pegs(self, show_labels: bool) -> None:
        """Draw pegs as rectangles perpendicular to cable direction."""
        if not self.layout:
            return

        # Group pegs by reason for legend tracking
        pegs_by_reason: dict[str, list[PegPosition]] = {}
        for peg in self.layout.pegs:
            reason_key = peg.reason.value if hasattr(peg.reason, "value") else str(peg.reason)
            if reason_key not in pegs_by_reason:
                pegs_by_reason[reason_key] = []
            pegs_by_reason[reason_key].append(peg)

        # Draw each peg as a rectangle
        for reason_key, pegs in pegs_by_reason.items():
            color = self.style.peg_colors.get(reason_key, self.style.peg_colors["UNSPECIFIED"])

            for index, peg in enumerate(pegs):
                self._draw_single_peg(peg, color, reason_key if index == 0 else None)

    def _draw_single_peg(
        self,
        peg: PegPosition,
        color: str,
        label: str | None
    ) -> None:
        """Draw a single peg as a rotated rectangle."""
        # Peg dimensions
        peg_width = self.style.peg_width_mm
        peg_length = self.style.peg_length_mm

        # Calculate rectangle corner (bottom-left before rotation)
        center_x = peg.position.x
        center_y = peg.position.y

        # Rectangle is centered at peg position
        rect_x = center_x - peg_length / 2
        rect_y = center_y - peg_width / 2

        # Create rectangle
        rectangle = patches.Rectangle(
            (rect_x, rect_y),
            peg_length,
            peg_width,
            facecolor=color,
            edgecolor="white",
            linewidth=1.0,
            zorder=6,
            label=f"Peg ({label})" if label else None,
        )

        # Apply rotation around the peg center
        transform = (
            patches.transforms.Affine2D()
            .rotate_deg_around(center_x, center_y, peg.orientation_deg)
            + self._axes.transData
        )
        rectangle.set_transform(transform)

        self._axes.add_patch(rectangle)

    def _add_legend(self) -> None:
        """Add legend to the plot."""
        # Collect legend handles
        handles = []
        labels = []

        # --- Topology Elements ---
        # Nodes (red diamonds)
        node_marker = plt.Line2D(
            [0], [0],
            marker="D",
            color="w",
            markerfacecolor=self.style.node_color,
            markersize=8,
            linestyle="None",
        )
        handles.append(node_marker)
        labels.append("Nodes (branch points)")

        # Connector holders (blue rectangles) - only if layout exists
        if self.layout and self.layout.connector_holders:
            connector_patch = patches.Patch(
                facecolor=self.style.connector_color,
                edgecolor=self.style.connector_edge_color,
                alpha=self.style.connector_alpha,
            )
            handles.append(connector_patch)
            labels.append("Connector holders")
        elif self.harness and self.harness.connector_occurrences:
            # CDM connectors without layout
            connector_patch = patches.Patch(
                facecolor=self.style.connector_color,
                edgecolor=self.style.connector_edge_color,
                alpha=self.style.connector_alpha,
            )
            handles.append(connector_patch)
            labels.append("Connectors")

        # Buffer zones (light blue circles)
        if self.layout and self.layout.connector_holders:
            buffer_circle = patches.Patch(
                facecolor=self.style.buffer_zone_color,
                alpha=self.style.buffer_zone_alpha,
            )
            handles.append(buffer_circle)
            labels.append("Buffer zones")

        # --- Peg Types ---
        if self.layout and self.layout.pegs:
            # Collect unique peg reasons
            peg_reasons = set()
            for peg in self.layout.pegs:
                reason_key = peg.reason.value if hasattr(peg.reason, "value") else str(peg.reason)
                peg_reasons.add(reason_key)

            # Create legend entry for each peg type
            for reason_key in sorted(peg_reasons):
                color = self.style.peg_colors.get(reason_key, self.style.peg_colors["UNSPECIFIED"])
                peg_patch = patches.Rectangle(
                    (0, 0), 1, 0.3,  # Small rectangle for legend
                    facecolor=color,
                    edgecolor="white",
                )
                handles.append(peg_patch)
                labels.append(f"Peg ({reason_key})")

        # --- Wire Types ---
        if self.harness and self.harness.connections:
            wire_colors_shown = set()
            for connection in self.harness.connections:
                if not connection.wire_occurrence:
                    continue

                wire_occ = connection.wire_occurrence
                wire_color = self._get_wire_color(wire_occ)

                # Get wire part number for label
                wire_label = wire_occ.wire.part_number if wire_occ.wire else wire_occ.id

                if wire_label not in wire_colors_shown:
                    wire_colors_shown.add(wire_label)
                    line = plt.Line2D(
                        [0], [0],
                        color=wire_color,
                        linewidth=2,
                    )
                    handles.append(line)
                    labels.append(f"Wire: {wire_label}")

        if handles:
            self._axes.legend(
                handles,
                labels,
                loc="upper left",
                bbox_to_anchor=(1.02, 1),
                fontsize=8,
                title="Legend",
                title_fontsize=9,
            )

    def export_png(self, filepath: str, dpi: int | None = None) -> None:
        """Export the visualization to a PNG file."""
        if self._figure is None:
            self.render()

        self._figure.savefig(
            filepath,
            dpi=dpi or self.style.figure_dpi,
            bbox_inches="tight",
            facecolor="white",
            edgecolor="none",
        )

    def export_pdf(self, filepath: str) -> None:
        """Export the visualization to a PDF file (vector graphics)."""
        if self._figure is None:
            self.render()

        self._figure.savefig(
            filepath,
            format="pdf",
            bbox_inches="tight",
            facecolor="white",
            edgecolor="none",
        )

    def export_svg(self, filepath: str) -> None:
        """Export the visualization to an SVG file."""
        if self._figure is None:
            self.render()

        self._figure.savefig(
            filepath,
            format="svg",
            bbox_inches="tight",
        )

    def show(self) -> None:
        """Display the visualization in an interactive window."""
        if self._figure is None:
            self.render()

        plt.show()

    def close(self) -> None:
        """Close the figure and free resources."""
        if self._figure is not None:
            plt.close(self._figure)
            self._figure = None
            self._axes = None


def plot_harness(
    harness: WireHarness,
    board_config: BoardConfig | None = None,
    layout: LayoutResponse | None = None,
    show_grid: bool = True,
    show_individual_wires: bool = True,
    show_labels: bool = True,
    title: str | None = None,
) -> None:
    """
    Convenience function to quickly visualize a wire harness.

    Args:
        harness: WireHarness CDM to visualize
        board_config: Optional board configuration. If None, auto-calculated from harness.
        layout: Optional LayoutResponse with pegs and connector holders
        show_grid: Whether to show grid overlay
        show_individual_wires: Whether to show individual wire paths
        show_labels: Whether to show element labels
        title: Optional custom title for the plot

    Example:
        >>> from layout_generator.visualizer import plot_harness
        >>> plot_harness(my_harness)
    """
    # Auto-calculate board config if not provided
    if board_config is None:
        if harness.nodes:
            all_x = [node.position.coord_x for node in harness.nodes]
            all_y = [node.position.coord_y for node in harness.nodes]

            padding = 100  # mm
            min_x = min(all_x) - padding
            max_x = max(all_x) + padding
            min_y = min(all_y) - padding
            max_y = max(all_y) + padding

            board_config = BoardConfig(
                width_mm=max(max_x - min_x, 200),
                height_mm=max(max_y - min_y, 200),
                offset_x=-min_x if min_x < 0 else 0,
                offset_y=-min_y if min_y < 0 else 0,
            )
        else:
            board_config = BoardConfig()

    visualizer = BoardLayoutVisualizer(board_config)
    visualizer.add_harness(harness)

    if layout:
        visualizer.add_layout(layout)

    visualizer.render(
        show_grid=show_grid,
        show_individual_wires=show_individual_wires,
        show_labels=show_labels,
    )

    if title:
        visualizer._axes.set_title(title)

    visualizer.show()
