"""ProjectModel schema tests."""

from anonymizer.model.project import ProjectModel


def test_project_model_v7_has_no_ai_feature_fields() -> None:
    model = ProjectModel()
    assert model.version == ProjectModel.MODEL_VERSION
    assert not hasattr(model, "remove_pixel_phi")
    assert not hasattr(model, "enable_harmonize")
    assert not hasattr(model, "enable_face_blur")
