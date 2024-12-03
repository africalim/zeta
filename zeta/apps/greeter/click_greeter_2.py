import os
import glob
from omegaconf import OmegaConf
import click
from scabha.schema_utils import clickify_parameters, paramfile_loader
from scabha.basetypes import File

command = "greet"

thisdir = os.path.dirname(__file__)

# Load additional configurations
source_files = glob.glob(f"{thisdir}/*.yaml")
sources = [File(item) for item in source_files]
parserfile = File( f"{thisdir}/{command}.yaml")
config = paramfile_loader(parserfile, sources)[command]


@click.command(command)
@clickify_parameters(config)
def runit(**kwargs):
    opts = OmegaConf.create(kwargs)
    click.echo(f'Hello, {opts.name}!')