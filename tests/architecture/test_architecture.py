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
        .defined_by_folder("api*")
        .layer("repositories")
        .defined_by_folder("modules/*/repositories*")
        .where_layer("api")
        .may_not_depend_on_layers("repositories")
    )
    testing.assert_passes(rule)


def test_layer_boundaries_repositories_do_not_depend_on_api():
    """Ensure repository data layer never imports or couples with API transport layer."""
    rule = (
        layers("src")
        .layer("api")
        .defined_by_folder("api*")
        .layer("repositories")
        .defined_by_folder("modules/*/repositories*")
        .where_layer("repositories")
        .may_not_depend_on_layers("api")
    )
    testing.assert_passes(rule)


def test_security_module_does_not_depend_on_repositories_or_api():
    """Ensure security gatekeeper never depends on database repositories or API transport layer."""
    rule = (
        layers("src")
        .layer("security")
        .defined_by_folder("modules/security*")
        .layer("repositories")
        .defined_by_folder("modules/*/repositories*")
        .layer("api")
        .defined_by_folder("api*")
        .where_layer("security")
        .may_not_depend_on_layers("repositories", "api")
    )
    testing.assert_passes(rule)


def test_security_module_does_not_depend_on_infrastructure():
    """Ensure security gatekeeper never couples with infrastructure clients (HTTP/LLM/Webhooks)."""
    rule = (
        layers("src")
        .layer("security")
        .defined_by_folder("modules/security*")
        .layer("infrastructure")
        .defined_by_folder("modules/infrastructure*")
        .where_layer("security")
        .may_not_depend_on_layers("infrastructure")
    )
    testing.assert_passes(rule)
