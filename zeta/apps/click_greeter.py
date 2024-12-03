import os
import glob
from omegaconf import OmegaConf
import click
from scabha.schema_utils import clickify_parameters, paramfile_loader

command = "greet"

thisdir = os.path.dirname(__file__)

# Load additional configurations
source_files = glob.glob(f"{thisdir}/*.yaml")
sources = [OmegaConf.load(item) for item in source_files]
parserfile = os.path.join(thisdir, "greet.yaml")
config = paramfile_loader(OmegaConf.load(parserfile), sources)[command]


@click.command()
#@click.argument('name')
@clickify_parameters(config)
def greet(**kwargs):
    opts = OmegaConf.create(kwargs)
    click.echo(f'Hello, {opts.name}!')