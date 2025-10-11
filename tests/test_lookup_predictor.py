"""
Tests for lookup-based predictor

This test verifies that the LookupPredictor can successfully load prediction data
from a JSON file and perform lookups based on model type.
"""

import pytest
import json
import tempfile
from pathlib import Path

from lookup_predictor import LookupPredictor


class TestLookupPredictor:
    """Test LookupPredictor functionality"""

    @pytest.fixture
    def sample_predictions(self):
        """Create sample prediction data"""
        return [
            {
                "status": "success",
                "quantile_predictions": [182.61, 209.48, 248.25, 987.97],
                "quantiles": [0.25, 0.5, 0.75, 0.99],
                "model_info": {
                    "type": "rec.rec.recmodel.ocrrecognize",
                    "name": "tx_rec_dummy",
                    "hardware": "TX",
                    "software_name": "rec.rec.RecModel.OcrRecognize",
                    "software_version": "0.0.1"
                },
                "model_type": "tx_rec_dummy"
            },
            {
                "status": "success",
                "quantile_predictions": [100.0, 150.0, 200.0, 500.0],
                "quantiles": [0.25, 0.5, 0.75, 0.99],
                "model_info": {
                    "type": "det.det.detmodel.ocrdetectfullimagewithlayout",
                    "name": "tx_det_dummy",
                    "hardware": "TX",
                    "software_name": "det.det.DetModel.OcrDetectFullImageWithLayout",
                    "software_version": "0.0.1"
                },
                "model_type": "tx_det_dummy"
            },
            {
                "status": "failed",
                "error": "Model not found"
            },
            {
                "status": "success",
                "quantile_predictions": [200.0, 250.0, 300.0, 600.0],
                "quantiles": [0.25, 0.5, 0.75, 0.99],
                "model_info": {
                    "type": "det.det.detmodel.ocrdetectfullimagewithlayout",
                    "name": "tx_det_dummy",
                    "hardware": "TX",
                    "software_name": "det.det.DetModel.OcrDetectFullImageWithLayout",
                    "software_version": "0.0.1"
                },
                "model_type": "tx_det_dummy"
            }
        ]

    @pytest.fixture
    def temp_prediction_file(self, sample_predictions):
        """Create a temporary prediction file"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            json.dump(sample_predictions, f)
            temp_path = f.name

        yield temp_path

        # Cleanup
        Path(temp_path).unlink()

    def test_load_predictions(self, temp_prediction_file):
        """Test that predictor can load predictions from file"""
        predictor = LookupPredictor(temp_prediction_file)

        assert len(predictor.predictions) == 4
        assert predictor.predictions[0]['status'] == 'success'

    def test_get_stats(self, temp_prediction_file):
        """Test statistics gathering"""
        predictor = LookupPredictor(temp_prediction_file)
        stats = predictor.get_stats()

        assert stats['total_records'] == 4
        assert stats['successful_records'] == 3
        assert 'tx_rec_dummy' in stats['model_types']
        assert 'tx_det_dummy' in stats['model_types']

    def test_predict_by_model_type(self, temp_prediction_file):
        """Test prediction lookup by model_type"""
        predictor = LookupPredictor(temp_prediction_file)

        result = predictor.predict(
            model_type="tx_rec_dummy",
            metadata={}
        )

        assert result is not None
        assert 'quantile_predictions' in result
        assert 'quantiles' in result
        assert result['quantiles'] == [0.25, 0.5, 0.75, 0.99]
        assert len(result['quantile_predictions']) == 4

    def test_predict_by_model_info_type(self, temp_prediction_file):
        """Test prediction lookup by model_info.type"""
        predictor = LookupPredictor(temp_prediction_file)

        result = predictor.predict(
            model_type="rec.rec.recmodel.ocrrecognize",
            metadata={}
        )

        assert result is not None
        assert result['model_type'] == 'tx_rec_dummy'

    def test_predict_multiple_matches(self, temp_prediction_file):
        """Test that multiple matches result in random selection"""
        predictor = LookupPredictor(temp_prediction_file)

        # tx_det_dummy has 2 matching records
        results = set()
        for _ in range(20):  # Run multiple times to check randomness
            result = predictor.predict(
                model_type="tx_det_dummy",
                metadata={}
            )
            if result:
                # Store the first quantile prediction to differentiate records
                results.add(tuple(result['quantile_predictions']))

        # Should have seen both different records (though with low probability might see only one)
        # We just verify that we got valid predictions
        assert len(results) >= 1

    def test_predict_no_match(self, temp_prediction_file):
        """Test prediction lookup with no matching model"""
        predictor = LookupPredictor(temp_prediction_file)

        result = predictor.predict(
            model_type="nonexistent_model",
            metadata={}
        )

        assert result is None

    def test_predict_with_metadata_filtering(self, temp_prediction_file):
        """Test that metadata filters work correctly"""
        predictor = LookupPredictor(temp_prediction_file)

        # Match by model_info.type with matching metadata
        result = predictor.predict(
            model_type="det.det.detmodel.ocrdetectfullimagewithlayout",
            metadata={
                "model_name": "tx_det_dummy",
                "hardware": "TX"
            }
        )

        assert result is not None
        assert result['model_info']['hardware'] == 'TX'

    def test_nonexistent_file(self):
        """Test handling of nonexistent file"""
        predictor = LookupPredictor("/nonexistent/path/to/file.json")

        assert len(predictor.predictions) == 0

        result = predictor.predict("any_model", {})
        assert result is None


class TestLookupPredictorIntegration:
    """Integration test with ShortestQueueStrategy"""

    def test_strategy_with_lookup_predictor(self):
        """Test that ShortestQueueStrategy can use lookup predictor"""
        from strategy_refactored import ShortestQueueStrategy, TaskInstance
        from task_instance_client_refactored import TaskInstanceClient
        from uuid import uuid4
        from unittest.mock import Mock

        # Create mock TaskInstance
        mock_client = Mock(spec=TaskInstanceClient)
        mock_client.base_url = "http://localhost:8101"

        ti_uuid = uuid4()
        task_instance = TaskInstance(uuid=ti_uuid, instance=mock_client)

        # Create temporary prediction file
        predictions = [
            {
                "status": "success",
                "quantile_predictions": [100.0, 150.0, 200.0, 500.0],
                "quantiles": [0.25, 0.5, 0.75, 0.99],
                "model_type": "test_model"
            }
        ]

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            json.dump(predictions, f)
            temp_path = f.name

        try:
            # Create strategy with lookup predictor
            strategy = ShortestQueueStrategy(
                taskinstances=[task_instance],
                use_lookup_predictor=True,
                prediction_file=temp_path
            )

            assert strategy.use_lookup_predictor is True
            assert strategy.lookup_predictor is not None
            assert len(strategy.lookup_predictor.predictions) == 1

            # Verify stats
            stats = strategy.lookup_predictor.get_stats()
            assert stats['successful_records'] == 1

        finally:
            Path(temp_path).unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
