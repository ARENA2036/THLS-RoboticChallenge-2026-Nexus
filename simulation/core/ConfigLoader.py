"""
JSON config loader with pydantic validation.
"""

import json
from pathlib import Path
from typing import Any, Dict

from .ConfigModels import (
    BoardSetupConfig,
    GrippersConfig,
    RobotsConfig,
    SceneObjectsConfig,
    StationConfig,
    WireRoutingConfig,
)


class ConfigLoader:
    def __init__(self, simulation_root_path: str) -> None:
        self.simulation_root_path = Path(simulation_root_path)
        self.config_dir_path = self.simulation_root_path / "config"

    def _read_json_file(self, file_name: str) -> Dict[str, Any]:
        file_path = self.config_dir_path / file_name
        with file_path.open("r", encoding="utf-8") as file_handle:
            return json.load(file_handle)

    def load_station_config(self, file_name: str = "station.default.json") -> StationConfig:
        return StationConfig.model_validate(self._read_json_file(file_name))

    def load_robots_config(self, file_name: str = "robots.default.json") -> RobotsConfig:
        return RobotsConfig.model_validate(self._read_json_file(file_name))

    def load_grippers_config(self, file_name: str = "grippers.default.json") -> GrippersConfig:
        return GrippersConfig.model_validate(self._read_json_file(file_name))

    def load_scene_objects_config(self, file_name: str = "scene_objects.default.json") -> SceneObjectsConfig:
        return SceneObjectsConfig.model_validate(self._read_json_file(file_name))

    def load_board_setup_config(self, file_name: str = "board_setup.default.json") -> BoardSetupConfig:
        return BoardSetupConfig.model_validate(self._read_json_file(file_name))

    def load_wire_routing_config(self, file_name: str = "wire_routing.default.json") -> WireRoutingConfig:
        return WireRoutingConfig.model_validate(self._read_json_file(file_name))
