from archunitpython import files, layers, testing


def test_no_circular_dependencies():
    """Ensure that the src codebase is completely free of circular dependencies."""
    rule = files("src").should().have_no_cycles()
    testing.assert_passes(rule)


def test_layer_boundaries_api_does_not_depend_on_repositories():
    """Ensure API layer never bypasses service layer to call repositories directly."""
    rule = (
        layers("src")
        .layer("api")
        .defined_by_folder("api")
        .layer("repositories")
        .defined_by_folder("modules/*/repositories")
        .where_layer("api")
        .may_not_depend_on_layers("repositories")
    )
    testing.assert_passes(rule)
