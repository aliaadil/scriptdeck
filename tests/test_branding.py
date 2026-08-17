def test_package_imports_as_kindling():
    import kindling
    assert kindling.__name__ == 'kindling'


def test_cli_command_name():
    from click.testing import CliRunner
    from kindling.cli import main
    runner = CliRunner()
    result = runner.invoke(main, ['--help'])
    assert result.exit_code == 0
    assert 'kindling' in result.output.lower()