"""Tests for the architect feature.

Covers the schema dataclasses, the loader (via the python-module-loader
widget), structural validation, the Mermaid renderer (via the mermaid
widget), and the scaffold writer.
"""

import os
from pathlib import Path

import pytest

from cartograph import architect


# ---------------------------------------------------------------------------
# Scaffold + load round-trip
# ---------------------------------------------------------------------------


def test_scaffold_writes_a_loadable_file(tmp_path):
    path = tmp_path / "architect.py"
    architect.write_architect_template(str(path))
    assert path.exists()
    arch = architect.load_architecture(str(path))
    assert isinstance(arch, architect.Architecture)
    assert arch.components, "scaffolded architecture should have components"
    issues = architect.validate_architecture(arch)
    assert issues == [], f"scaffolded architecture should validate: {issues}"


def test_scaffold_refuses_to_overwrite(tmp_path):
    path = tmp_path / "architect.py"
    path.write_text("# existing\n")
    with pytest.raises(FileExistsError):
        architect.write_architect_template(str(path))


def test_scaffold_overwrites_when_forced(tmp_path):
    path = tmp_path / "architect.py"
    path.write_text("# existing\n")
    architect.write_architect_template(str(path), overwrite=True)
    assert "Architecture(" in path.read_text()


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def test_resolve_explicit_path():
    out = architect.resolve_architect_path("relative/path.py")
    assert os.path.isabs(out)
    assert out.endswith(os.path.join("relative", "path.py"))


def test_resolve_default_uses_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = architect.resolve_architect_path()
    assert out == str(tmp_path / "architect.py")


def test_resolve_explicit_directory_appends_filename(tmp_path):
    out = architect.resolve_architect_path(str(tmp_path))
    assert out == str(tmp_path / "architect.py")


# ---------------------------------------------------------------------------
# Loader error surfacing
# ---------------------------------------------------------------------------


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(architect.ArchitectLoadError) as exc:
        architect.load_architecture(str(tmp_path / "nope.py"))
    assert "init" in str(exc.value)


def test_load_no_architecture_instance_raises(tmp_path):
    path = tmp_path / "architect.py"
    path.write_text("x = 1\n")
    with pytest.raises(architect.ArchitectLoadError) as exc:
        architect.load_architecture(str(path))
    assert "Architecture" in str(exc.value)


def test_load_multiple_architecture_instances_raises(tmp_path):
    body = (
        "from cartograph.architect.schema import Architecture\n"
        "first = Architecture()\n"
        "second = Architecture()\n"
    )
    path = tmp_path / "architect.py"
    path.write_text(body)
    with pytest.raises(architect.ArchitectLoadError) as exc:
        architect.load_architecture(str(path))
    assert "more than one" in str(exc.value)


def test_load_syntax_error_raises(tmp_path):
    path = tmp_path / "architect.py"
    path.write_text("def broken(:\n")
    with pytest.raises(architect.ArchitectLoadError):
        architect.load_architecture(str(path))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _arch(**kw):
    return architect.Architecture(**kw)


def test_empty_architecture_validates():
    issues = architect.validate_architecture(_arch())
    assert issues == []


def test_unknown_schema_version_flagged():
    issues = architect.validate_architecture(_arch(schema_version="9.99"))
    codes = [i.code for i in issues]
    assert "schema_version" in codes


def test_duplicate_component_id_flagged():
    arch = _arch(components=[
        architect.Component(id="a"),
        architect.Component(id="a"),
    ])
    codes = [i.code for i in architect.validate_architecture(arch)]
    assert "component_id" in codes


def test_blank_component_id_flagged():
    arch = _arch(components=[architect.Component(id="")])
    codes = [i.code for i in architect.validate_architecture(arch)]
    assert "component_id" in codes


def test_dangling_parent_flagged():
    arch = _arch(components=[
        architect.Component(id="leaf", parent="ghost"),
    ])
    codes = [i.code for i in architect.validate_architecture(arch)]
    assert "parent_ref" in codes


def test_parent_cycle_flagged():
    arch = _arch(components=[
        architect.Component(id="a", parent="b"),
        architect.Component(id="b", parent="a"),
    ])
    codes = [i.code for i in architect.validate_architecture(arch)]
    assert "parent_cycle" in codes


def test_dangling_edge_source_flagged():
    arch = _arch(
        components=[architect.Component(id="a")],
        edges=[architect.Edge(source="ghost", target="a")],
    )
    codes = [i.code for i in architect.validate_architecture(arch)]
    assert "edge_source" in codes


def test_dangling_edge_target_flagged():
    arch = _arch(
        components=[architect.Component(id="a")],
        edges=[architect.Edge(source="a", target="ghost")],
    )
    codes = [i.code for i in architect.validate_architecture(arch)]
    assert "edge_target" in codes


def test_unknown_domain_flagged():
    arch = _arch(components=[
        architect.Component(id="a", domains=["not-a-domain"]),
    ])
    codes = [i.code for i in architect.validate_architecture(arch)]
    assert "domain" in codes


def test_known_domains_pass():
    arch = _arch(components=[
        architect.Component(id="a", domains=["backend"]),
        architect.Component(id="b", domains=["modeling"]),
        architect.Component(id="c", domains=["rtl"]),
    ])
    issues = architect.validate_architecture(arch)
    assert issues == []


def test_empty_domains_list_ignored():
    arch = _arch(components=[
        architect.Component(id="a"),
        architect.Component(id="b", domains=[]),
    ])
    assert architect.validate_architecture(arch) == []


def test_glue_domain_accepted():
    arch = _arch(components=[
        architect.Component(id="a", domains=["glue"]),
    ])
    assert architect.validate_architecture(arch) == []


def test_multi_domain_accepted():
    arch = _arch(components=[
        architect.Component(id="a", domains=["data", "ml"]),
        architect.Component(id="b", domains=["backend", "glue"]),
    ])
    assert architect.validate_architecture(arch) == []


def test_multi_domain_with_one_invalid_flagged():
    arch = _arch(components=[
        architect.Component(id="a", domains=["backend", "garbage"]),
    ])
    codes = [i.code for i in architect.validate_architecture(arch)]
    assert "domain" in codes


def test_duplicate_domain_in_list_flagged():
    arch = _arch(components=[
        architect.Component(id="a", domains=["backend", "backend"]),
    ])
    codes = [i.code for i in architect.validate_architecture(arch)]
    assert "domain" in codes


def test_empty_string_domain_entry_flagged():
    arch = _arch(components=[
        architect.Component(id="a", domains=[""]),
    ])
    codes = [i.code for i in architect.validate_architecture(arch)]
    assert "domain" in codes


def test_format_issues_renders_codes_and_messages():
    issues = architect.validate_architecture(_arch(
        components=[
            architect.Component(id="a"),
            architect.Component(id="a"),
        ],
    ))
    text = architect.format_issues(issues)
    assert "[component_id]" in text
    assert "Duplicate" in text


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def test_render_minimal():
    out = architect.render(_arch(components=[
        architect.Component(id="a"),
        architect.Component(id="b"),
    ], edges=[
        architect.Edge(source="a", target="b", kind="depends_on"),
    ]))
    assert "flowchart TD" in out
    assert 'a["a"]' in out
    assert 'a -->|"depends_on"| b' in out


def test_render_groups_children_under_parent_cluster():
    out = architect.render(_arch(components=[
        architect.Component(id="server"),
        architect.Component(id="api", parent="server"),
        architect.Component(id="db", parent="server"),
    ]))
    assert "subgraph server" in out
    server_block = out.split("subgraph server", 1)[1]
    assert 'api[' in server_block.split("\n    end", 1)[0]
    assert 'db[' in server_block.split("\n    end", 1)[0]


def test_render_edge_can_target_a_parent_component():
    out = architect.render(_arch(components=[
        architect.Component(id="user"),
        architect.Component(id="server"),
        architect.Component(id="api", parent="server"),
    ], edges=[
        architect.Edge(source="user", target="server", kind="calls"),
    ]))
    assert 'user -->|"calls"| server' in out


def test_render_emits_classdef_for_used_domains_only():
    out = architect.render(_arch(components=[
        architect.Component(id="a", domains=["backend"]),
        architect.Component(id="b"),
    ]))
    assert "classDef backend" in out
    assert "classDef modeling" not in out


def test_render_glue_domain_styled():
    out = architect.render(_arch(components=[
        architect.Component(id="a", domains=["glue"]),
    ]))
    assert "classDef glue" in out
    assert ":::glue" in out
    assert "stroke-dasharray" in out


def test_render_multi_domain_picks_glue_when_present():
    out = architect.render(_arch(components=[
        architect.Component(id="a", domains=["backend", "glue"]),
    ]))
    assert ":::glue" in out
    assert ":::backend" not in out


def test_render_multi_domain_picks_first_known_when_no_glue():
    out = architect.render(_arch(components=[
        architect.Component(id="a", domains=["data", "ml"]),
    ]))
    assert ":::data" in out
    assert ":::ml" not in out


def test_render_multi_domain_label_shows_all_domains():
    out = architect.render(_arch(components=[
        architect.Component(id="a", domains=["backend", "glue"]),
    ]))
    assert "(backend, glue)" in out


def test_render_single_domain_label_does_not_show_domain_tag():
    out = architect.render(_arch(components=[
        architect.Component(id="a", domains=["backend"]),
    ]))
    assert "(backend)" not in out


def test_render_direction_lr():
    out = architect.render(
        _arch(components=[architect.Component(id="a")]),
        direction="LR",
    )
    assert "flowchart LR" in out


def test_render_round_trips_from_scaffold(tmp_path):
    path = tmp_path / "architect.py"
    architect.write_architect_template(str(path))
    arch = architect.load_architecture(str(path))
    out = architect.render(arch)
    assert "flowchart" in out
    assert "subgraph" in out


# ---------------------------------------------------------------------------
# Widget attachment - validation
# ---------------------------------------------------------------------------


def _install_fake_widget(tmp_path, widget_dir_name):
    """Create a cg/<widget_dir_name>/widget.json under tmp_path."""
    widget_dir = tmp_path / "cg" / widget_dir_name
    widget_dir.mkdir(parents=True)
    (widget_dir / "widget.json").write_text('{"id": "fake"}')
    return str(tmp_path)


def test_widget_attached_to_installed_widget_validates(tmp_path):
    project_root = _install_fake_widget(tmp_path, "fake_widget")
    arch = _arch(components=[
        architect.Component(
            id="api", domains=["backend"], widgets=["fake_widget"],
        ),
    ])
    issues = architect.validate_architecture(arch, project_root=project_root)
    assert issues == []


def test_multiple_widgets_attached_validates(tmp_path):
    _install_fake_widget(tmp_path, "router")
    _install_fake_widget(tmp_path, "validator")
    _install_fake_widget(tmp_path, "logger")
    arch = _arch(components=[
        architect.Component(
            id="api",
            domains=["backend"],
            widgets=["router", "validator", "logger"],
        ),
    ])
    issues = architect.validate_architecture(
        arch, project_root=str(tmp_path)
    )
    assert issues == []


def test_widget_missing_directory_flagged(tmp_path):
    arch = _arch(components=[
        architect.Component(id="api", widgets=["not_installed"]),
    ])
    codes = [
        i.code for i in architect.validate_architecture(
            arch, project_root=str(tmp_path)
        )
    ]
    assert "widget_missing" in codes


def test_one_missing_among_many_flagged(tmp_path):
    _install_fake_widget(tmp_path, "good")
    arch = _arch(components=[
        architect.Component(id="api", widgets=["good", "not_installed"]),
    ])
    codes = [
        i.code for i in architect.validate_architecture(
            arch, project_root=str(tmp_path)
        )
    ]
    assert "widget_missing" in codes


def test_widget_directory_without_manifest_flagged(tmp_path):
    (tmp_path / "cg" / "fake_widget").mkdir(parents=True)
    arch = _arch(components=[
        architect.Component(id="api", widgets=["fake_widget"]),
    ])
    codes = [
        i.code for i in architect.validate_architecture(
            arch, project_root=str(tmp_path)
        )
    ]
    assert "widget_invalid" in codes


def test_widgets_plus_glue_is_a_conflict(tmp_path):
    project_root = _install_fake_widget(tmp_path, "fake_widget")
    arch = _arch(components=[
        architect.Component(
            id="api",
            domains=["backend", "glue"],
            widgets=["fake_widget"],
        ),
    ])
    codes = [
        i.code for i in architect.validate_architecture(
            arch, project_root=project_root
        )
    ]
    assert "widget_glue_conflict" in codes


def test_duplicate_widget_in_list_flagged(tmp_path):
    project_root = _install_fake_widget(tmp_path, "fake_widget")
    arch = _arch(components=[
        architect.Component(
            id="api", widgets=["fake_widget", "fake_widget"],
        ),
    ])
    codes = [
        i.code for i in architect.validate_architecture(
            arch, project_root=project_root
        )
    ]
    assert "widget_duplicate" in codes


def test_empty_widgets_list_does_not_check_filesystem(tmp_path):
    arch = _arch(components=[
        architect.Component(id="api", domains=["backend"]),
    ])
    issues = architect.validate_architecture(
        arch, project_root=str(tmp_path)
    )
    assert issues == []


# ---------------------------------------------------------------------------
# Widget attachment - rendering
# ---------------------------------------------------------------------------


def test_render_widget_attached_shows_diamond_marker():
    out = architect.render(_arch(components=[
        architect.Component(id="api", widgets=["some_widget"]),
    ]))
    assert "◆" in out
    assert "some_widget" in out


def test_render_multiple_widgets_listed_in_label():
    out = architect.render(_arch(components=[
        architect.Component(id="api", widgets=["w1", "w2", "w3"]),
    ]))
    assert "◆" in out
    assert "w1, w2, w3" in out


def test_render_no_widgets_no_marker():
    out = architect.render(_arch(components=[
        architect.Component(id="api", domains=["backend"]),
    ]))
    assert "◆" not in out


def test_render_single_widget_emits_click_target():
    out = architect.render(_arch(components=[
        architect.Component(id="api", widgets=["cg_router"]),
    ]))
    assert 'click api href "cg/cg_router/"' in out


def test_render_multi_widget_skips_click_target():
    out = architect.render(_arch(components=[
        architect.Component(id="api", widgets=["cg_router", "cg_validator"]),
    ]))
    assert "click api" not in out


def test_render_no_widgets_no_click():
    out = architect.render(_arch(components=[
        architect.Component(id="api", domains=["backend"]),
    ]))
    assert "click" not in out


# ---------------------------------------------------------------------------
# Widget attachment - source mutation (attach/detach)
# ---------------------------------------------------------------------------


_MUTATE_FIXTURE = '''"""Test arch."""

from cartograph.architect.schema import Architecture, Component, Edge

# Top-level comment that must survive
architecture = Architecture(
    schema_version="0.1",
    goal="Demo project.",
    components=[
        Component(
            id="api",
            kind="service",
            domains=["backend"],
            description="Request handler.",
        ),
        Component(
            id="store",
            kind="datastore",
            domains=["data"],
        ),
    ],
    edges=[
        Edge(source="api", target="store", kind="reads_writes"),
    ],
)
'''


def test_set_widgets_writes_list_field():
    out = architect.set_component_widgets(
        _MUTATE_FIXTURE, "api", ["cg_router", "cg_validator"]
    )
    assert "widgets=" in out
    assert "cg_router" in out
    assert "cg_validator" in out
    assert "Top-level comment that must survive" in out
    assert 'id="store"' in out


def test_set_widgets_empty_list_clears_field():
    attached = architect.set_component_widgets(
        _MUTATE_FIXTURE, "api", ["cg_some_widget"]
    )
    cleared = architect.set_component_widgets(attached, "api", [])
    assert "cg_some_widget" not in cleared
    assert "widgets=" not in cleared
    assert "Top-level comment that must survive" in cleared


def test_set_widgets_replaces_existing_list():
    first = architect.set_component_widgets(
        _MUTATE_FIXTURE, "api", ["cg_a", "cg_b"]
    )
    second = architect.set_component_widgets(first, "api", ["cg_c"])
    assert "cg_c" in second
    assert "cg_a" not in second
    assert "cg_b" not in second


def test_set_widgets_round_trips_through_load(tmp_path):
    path = tmp_path / "architect.py"
    path.write_text(_MUTATE_FIXTURE)
    new_src = architect.set_component_widgets(
        path.read_text(), "api", ["w1", "w2"]
    )
    path.write_text(new_src)
    arch = architect.load_architecture(str(path))
    api = next(c for c in arch.components if c.id == "api")
    assert api.widgets == ["w1", "w2"]
    store = next(c for c in arch.components if c.id == "store")
    assert store.widgets == []


def test_set_widgets_unknown_component_raises():
    with pytest.raises(architect.ArchitectMutationError) as exc:
        architect.set_component_widgets(_MUTATE_FIXTURE, "ghost", ["w1"])
    assert "ghost" in str(exc.value)


def test_set_widgets_on_invalid_python_raises():
    with pytest.raises(architect.ArchitectMutationError):
        architect.set_component_widgets("def broken(:", "api", ["w1"])


# ---------------------------------------------------------------------------
# Multi-line pretty unparser
# ---------------------------------------------------------------------------


def test_mutated_component_is_multi_line():
    out = architect.set_component_widgets(
        _MUTATE_FIXTURE, "api", ["cg_router"]
    )
    api_block = out.split("Component(", 1)[1].split("),", 1)[0]
    # Block should contain at least one newline - it's multi-line.
    assert "\n" in api_block


def test_mutated_widgets_list_expands_when_multi():
    out = architect.set_component_widgets(
        _MUTATE_FIXTURE, "api", ["w1", "w2", "w3"]
    )
    # Each widget should be on its own line inside a [\n ... \n] form.
    assert "'w1'," in out
    assert "'w2'," in out
    assert "'w3'," in out


def test_mutated_single_widget_list_stays_inline():
    out = architect.set_component_widgets(
        _MUTATE_FIXTURE, "api", ["only_one"]
    )
    # A single-element list shouldn't blow up vertically.
    assert "widgets=['only_one']" in out


def test_mutated_keeps_base_indent():
    indented = "        " + _MUTATE_FIXTURE.replace("\n        Component", "\n                Component")
    # Build a fixture where Component is at a deeper indent and verify
    # the mutator preserves that indent for the closing paren.
    src = """architecture = (
            Component(
                id="api",
                kind="service",
            )
        )
"""
    out = architect.set_component_widgets(src, "api", ["w1"])
    # The closing paren should align with the original Component(.
    assert "            )" in out


# ---------------------------------------------------------------------------
# Parent Component rendering with widgets
# ---------------------------------------------------------------------------


def test_render_parent_component_shows_widgets_in_cluster_label():
    out = architect.render(_arch(components=[
        architect.Component(
            id="dispatcher",
            kind="subsystem",
            widgets=["cg_resolver"],
        ),
        architect.Component(
            id="child",
            kind="engine",
            parent="dispatcher",
        ),
    ]))
    # Cluster header should show diamond, id, kind, and widget.
    assert "subgraph dispatcher" in out
    cluster_block = out.split("subgraph dispatcher", 1)[1].split("end", 1)[0]
    assert "◆ dispatcher" in cluster_block
    assert "[subsystem]" in cluster_block
    assert "<cg_resolver>" in cluster_block


def test_render_parent_component_id_in_cluster_label():
    out = architect.render(_arch(components=[
        architect.Component(id="parent", kind="grouping"),
        architect.Component(id="child", parent="parent"),
    ]))
    # Cluster label is multi-line: id on one line, [kind] on the next.
    block = out.split("subgraph parent", 1)[1].split("end", 1)[0]
    assert "parent" in block
    assert "[grouping]" in block


# ---------------------------------------------------------------------------
# Shape vocabulary by kind
# ---------------------------------------------------------------------------


def test_render_external_kind_uses_stadium_shape():
    out = architect.render(_arch(components=[
        architect.Component(id="dev", kind="external"),
    ]))
    assert 'dev(["dev' in out


def test_render_datastore_kind_uses_cylinder_shape():
    out = architect.render(_arch(components=[
        architect.Component(id="db", kind="datastore"),
    ]))
    assert 'db[("db' in out


def test_render_service_kind_uses_rounded_shape():
    out = architect.render(_arch(components=[
        architect.Component(id="api", kind="service"),
    ]))
    assert 'api("api' in out


def test_render_engine_kind_uses_rounded_shape():
    out = architect.render(_arch(components=[
        architect.Component(id="eng", kind="engine"),
    ]))
    assert 'eng("eng' in out


def test_render_pipeline_kind_uses_rounded_shape():
    out = architect.render(_arch(components=[
        architect.Component(id="p", kind="pipeline"),
    ]))
    assert 'p("p' in out


def test_render_policy_kind_uses_rhombus_shape():
    out = architect.render(_arch(components=[
        architect.Component(id="auth", kind="policy"),
    ]))
    assert 'auth{"auth' in out


def test_render_unknown_kind_falls_back_to_rectangle():
    out = architect.render(_arch(components=[
        architect.Component(id="thing", kind="custom_made_up_kind"),
    ]))
    # Default rectangle uses [...] wrapping.
    assert 'thing["thing' in out


# ---------------------------------------------------------------------------
# Edge styling by kind
# ---------------------------------------------------------------------------


def test_render_reads_writes_uses_thick_arrow():
    out = architect.render(_arch(
        components=[
            architect.Component(id="a"),
            architect.Component(id="b"),
        ],
        edges=[architect.Edge(source="a", target="b", kind="reads_writes")],
    ))
    assert " ==>" in out


def test_render_enforces_uses_thick_arrow():
    out = architect.render(_arch(
        components=[
            architect.Component(id="a"),
            architect.Component(id="b"),
        ],
        edges=[architect.Edge(source="a", target="b", kind="enforces")],
    ))
    assert " ==>" in out


def test_render_hosted_on_uses_dotted_arrow():
    out = architect.render(_arch(
        components=[
            architect.Component(id="a"),
            architect.Component(id="b"),
        ],
        edges=[architect.Edge(source="a", target="b", kind="hosted_on")],
    ))
    assert " -.->" in out


def test_render_served_by_uses_dotted_arrow():
    out = architect.render(_arch(
        components=[
            architect.Component(id="a"),
            architect.Component(id="b"),
        ],
        edges=[architect.Edge(source="a", target="b", kind="served_by")],
    ))
    assert " -.->" in out


def test_render_default_kind_uses_solid_arrow():
    out = architect.render(_arch(
        components=[
            architect.Component(id="a"),
            architect.Component(id="b"),
        ],
        edges=[architect.Edge(source="a", target="b", kind="delegates_to")],
    ))
    # Solid arrow rendered without thick/dotted markers.
    assert " --> " in out or ' -->|' in out
    assert " ==>" not in out
    assert " -.->" not in out


# ---------------------------------------------------------------------------
# Legend
# ---------------------------------------------------------------------------


def test_render_emits_legend_subgraph_when_anything_used():
    out = architect.render(_arch(components=[
        architect.Component(id="dev", kind="external"),
    ]))
    assert 'subgraph _legend["Legend"]' in out


def _legend_block(out: str) -> str:
    """Slice the legend subgraph body. Splits on '\\nend' (the line
    terminator) to avoid breaking on the substring 'end' inside 'Legend'.
    """
    after = out.split("subgraph _legend", 1)[1]
    return after.split("\nend", 1)[0]


def test_render_legend_includes_used_domain_swatch():
    out = architect.render(_arch(components=[
        architect.Component(id="api", kind="service", domains=["backend"]),
    ]))
    legend = _legend_block(out)
    assert "_legend_domain_backend" in legend


def test_render_legend_includes_used_shape_entry():
    out = architect.render(_arch(components=[
        architect.Component(id="db", kind="datastore"),
    ]))
    legend = _legend_block(out)
    # Cylinder demo node uses the cylinder shape itself.
    assert "_legend_shape_cylinder" in legend
    assert '[("datastore")]' in legend


def test_render_legend_includes_used_edge_demo():
    out = architect.render(_arch(
        components=[
            architect.Component(id="a"),
            architect.Component(id="b"),
        ],
        edges=[architect.Edge(source="a", target="b", kind="hosted_on")],
    ))
    # Legend cluster present.
    assert 'subgraph _legend["Legend"]' in out
    # Real arrow rendered between the legend pair.
    assert "_legend_edge_dpdg_a -.-> _legend_edge_dpdg_b" in out


def test_render_legend_omitted_when_no_styled_elements():
    # Plain components with no domains, no styled kinds, no styled edges:
    # nothing for the legend to describe, so no legend subgraph.
    out = architect.render(_arch(
        components=[
            architect.Component(id="a", kind="thing"),
            architect.Component(id="b", kind="other"),
        ],
        edges=[architect.Edge(source="a", target="b", kind="delegates_to")],
    ))
    assert "subgraph _legend" not in out


def test_render_legend_does_not_repeat_unused_styles():
    out = architect.render(_arch(components=[
        architect.Component(id="dev", kind="external"),
    ]))
    legend = _legend_block(out)
    # Only stadium used; cylinder/rhombus/rounded should not appear.
    assert "_legend_shape_stadium" in legend
    assert "_legend_shape_cylinder" not in legend
    assert "_legend_shape_rhombus" not in legend
    assert "_legend_shape_rounded" not in legend
