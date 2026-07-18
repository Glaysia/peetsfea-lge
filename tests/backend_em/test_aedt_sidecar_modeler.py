from __future__ import annotations

from ._aedt_sidecar_support import (
    test_cover_lines_thicken_sheet_and_unite_raise_when_legacy_signatures_are_unsupported,
    test_create_box_raises_when_non_model_keyword_is_unsupported,
    test_create_report_edit_sources_and_insert_helpers_validate_names,
    test_false_return_helpers_raise_and_validate_names,
    test_failfast_helpers_enforce_name_limit,
    test_modeler_geometry_helpers_raise_on_false,
    test_modeler_geometry_name_validators_cover_mutation_surfaces,
    test_set_object_color_sets_rgb_tuple,
    test_set_object_transparency_sets_float,
    test_sidecar_protocol_and_proxy_exports_are_explicit,
    test_top_level_reexports_match_aedt_submodules,
    test_unite_short_circuits_single_target_and_rejects_empty_targets,
)

