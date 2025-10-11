"""
Lookup-based Predictor for Scheduler

This module provides a simple table lookup predictor that reads prediction data
from a JSON file instead of calling the Predictor API. This simplifies the
prediction process and reduces latency.
"""

import json
import random
from typing import Dict, Any, List, Optional
from pathlib import Path
from loguru import logger


class LookupPredictor:
    """
    Lookup-based predictor that reads predictions from a JSON file

    The predictor loads prediction records from a JSON file and provides
    a lookup mechanism to find matching predictions based on model information.
    If multiple matches are found, one is randomly selected.
    """

    def __init__(self, prediction_file: str):
        """
        Initialize the lookup predictor

        Args:
            prediction_file: Path to the prediction JSON file
        """
        self.prediction_file = Path(prediction_file)
        self.predictions: List[Dict[str, Any]] = []
        self._load_predictions()

    def _load_predictions(self):
        """Load predictions from JSON file"""
        if not self.prediction_file.exists():
            logger.warning(f"Prediction file not found: {self.prediction_file}")
            return

        try:
            with open(self.prediction_file, 'r') as f:
                self.predictions = json.load(f)

            logger.info(
                f"Loaded {len(self.predictions)} prediction records from {self.prediction_file}"
            )
        except Exception as e:
            logger.error(f"Failed to load prediction file {self.prediction_file}: {e}")
            self.predictions = []

    def predict(
        self,
        model_type: str,
        metadata: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Lookup prediction for the given model type and metadata

        This method searches for matching predictions based on:
        1. model_type (exact match)
        2. model_info fields if available in metadata

        If multiple matches are found, one is randomly selected.

        Args:
            model_type: The model type to match
            metadata: Task metadata containing model information

        Returns:
            Prediction dictionary with quantiles and quantile_predictions,
            or None if no match found
        """
        if not self.predictions:
            logger.warning("No predictions loaded, cannot perform lookup")
            return None

        # Find all matching predictions
        matches = self._find_matches(model_type, metadata)

        if not matches:
            logger.debug(
                f"No prediction matches found for model_type={model_type}, "
                f"metadata keys={list(metadata.keys())}"
            )
            return None

        # Randomly select one if multiple matches
        selected = random.choice(matches)

        logger.debug(
            f"Found {len(matches)} matching predictions for model_type={model_type}, "
            f"randomly selected one with quantile_predictions={selected.get('quantile_predictions')}"
        )

        return selected

    def _find_matches(
        self,
        model_type: str,
        metadata: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Find all matching predictions

        Matching criteria:
        1. Primary: match by model_type field
        2. Secondary: match by model_info.type field
        3. Additional: match model_info fields if available in metadata

        Args:
            model_type: Model type to match
            metadata: Task metadata

        Returns:
            List of matching prediction records
        """
        matches = []

        # Extract model info from metadata if available
        model_name = metadata.get('model_name')
        hardware = metadata.get('hardware')
        software_name = metadata.get('software_name')
        software_version = metadata.get('software_version')

        for pred in self.predictions:
            # Skip failed predictions
            if pred.get('status') != 'success':
                continue

            # Check if quantile data is available
            if 'quantile_predictions' not in pred or 'quantiles' not in pred:
                continue

            # Match by model_type field (direct match)
            if pred.get('model_type') == model_type:
                matches.append(pred)
                continue

            # Match by model_info.type field
            model_info = pred.get('model_info', {})
            if model_info.get('type') == model_type:
                # If we have additional metadata, try to match more precisely
                if model_name and model_info.get('name') != model_name:
                    continue
                if hardware and model_info.get('hardware') != hardware:
                    continue
                if software_name and model_info.get('software_name') != software_name:
                    continue
                if software_version and model_info.get('software_version') != software_version:
                    continue

                matches.append(pred)

        return matches

    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about loaded predictions

        Returns:
            Dictionary with statistics
        """
        if not self.predictions:
            return {
                "total_records": 0,
                "successful_records": 0,
                "model_types": []
            }

        successful = [p for p in self.predictions if p.get('status') == 'success']
        model_types = set()

        for pred in successful:
            if 'model_type' in pred:
                model_types.add(pred['model_type'])
            if 'model_info' in pred and 'type' in pred['model_info']:
                model_types.add(pred['model_info']['type'])

        return {
            "total_records": len(self.predictions),
            "successful_records": len(successful),
            "model_types": sorted(list(model_types))
        }
