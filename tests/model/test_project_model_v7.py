"""ProjectModel schema tests."""

from anonymizer.model.project import JPEG2000_TRANSFER_SYNTAXES, ProjectModel

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


def test_opt_modality_sets_oct_storage_classes() -> None:
    """Enabling OPT fills the three ophthalmic tomography SOP classes (no Harmonize)."""
    _opt_image = "1.2.840.10008.5.1.4.1.1.77.1.5.4"
    _oct_en_face = "1.2.840.10008.5.1.4.1.1.77.1.5.7"
    _oct_bscan = "1.2.840.10008.5.1.4.1.1.77.1.5.8"
    model = ProjectModel(modalities=["OPT"], storage_classes=[])
    model.set_storage_classes_from_modalities()
    assert _opt_image in model.storage_classes
    assert _oct_en_face in model.storage_classes
    assert _oct_bscan in model.storage_classes


def test_op_modality_sets_photography_storage_classes() -> None:
    """Enabling OP fills the ophthalmic photography SOP classes (no Harmonize)."""
    _op_8bit = "1.2.840.10008.5.1.4.1.1.77.1.5.1"
    _op_16bit = "1.2.840.10008.5.1.4.1.1.77.1.5.2"
    _op_wide_stereo = "1.2.840.10008.5.1.4.1.1.77.1.5.5"
    _op_wide_3d = "1.2.840.10008.5.1.4.1.1.77.1.5.6"
    model = ProjectModel(modalities=["OP"], storage_classes=[])
    model.set_storage_classes_from_modalities()
    assert _op_8bit in model.storage_classes
    assert _op_16bit in model.storage_classes
    assert _op_wide_stereo in model.storage_classes
    assert _op_wide_3d in model.storage_classes


def test_ensure_jpeg2000_for_ophthalmic_modalities() -> None:
    """OP/OPT append JPEG 2000 transfer syntaxes; other modalities leave the list alone."""
    defaults = list(ProjectModel.default_transfer_syntaxes())
    model = ProjectModel(modalities=["CT"], transfer_syntaxes=list(defaults))
    assert model.ensure_jpeg2000_for_ophthalmic_modalities() is False
    assert model.transfer_syntaxes == defaults

    for code in ("OP", "OPT"):
        model = ProjectModel(modalities=[code], transfer_syntaxes=list(defaults))
        assert model.ensure_jpeg2000_for_ophthalmic_modalities() is True
        for uid in JPEG2000_TRANSFER_SYNTAXES:
            assert uid in model.transfer_syntaxes
        # Second call is a no-op once UIDs are present.
        assert model.ensure_jpeg2000_for_ophthalmic_modalities() is False
