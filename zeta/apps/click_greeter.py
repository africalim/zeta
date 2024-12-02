import click

@click.command()
@click.argument('name')
def greet(name):
    click.echo(f'Hello, {name}!')