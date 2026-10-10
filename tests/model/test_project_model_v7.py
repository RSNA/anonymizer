"""ProjectModel schema tests."""

from anonymizer.model.project import ProjectModel

_DOSE_SR = "1.2.840.10008.5.1.4.1.1.88.67"
_CUSTOM_EXTRA = "1.2.840.10008.5.1.4.1.1.7"  # Secondary Capture


def test_project_model_v7_has_no_ai_feature_fields() -> None:
    model = ProjectModel()
    assert model.version == ProjectModel.MODEL_VERSION
    assert not hasattr(model, "remove_pixel_phi")
    assert not hasattr(model, "enable_harmonize")
    assert not hasattr(model, "enable_face_blur")


def test_post_init_preserves_custom_storage_classes() -> None:
    model = ProjectModel(modalities=["CT"], storage_classes=[_CUSTOM_EXTRA])
    assert model.storage_classes == [_CUSTOM_EXTRA]


def test_ensure_storage_classes_adds_without_wiping_extras() -> None:
    model = ProjectModel(modalities=["CT"], storage_classes=[_CUSTOM_EXTRA])
    model.modalities = ["CT", "SR"]
    model.ensure_storage_classes_from_modalities()
    assert _CUSTOM_EXTRA in model.storage_classes
    assert _DOSE_SR in model.storage_classes
