import os
import glob
from omegaconf import OmegaConf
import click
from scabha.schema_utils import clickify_parameters, paramfile_loader
from scabha.basetypes import File
import numpy as np

command = "predict"

thisdir = os.path.dirname(__file__)

# Load additional configurations
source_files = glob.glob(f"{thisdir}/*.yaml")
sources = [File(item) for item in source_files]
parserfile = File( f"{thisdir}/{command}.yaml")
config = paramfile_loader(parserfile, sources)[command]


class Source:
    def __init__(self, ra: float, dec: float, flux: float, alpha: float, ref_freq: float):
        self.ra = ra
        self.dec = dec
        self.flux = flux
        self.alpha = alpha
        self.ref_freq = ref_freq
        self.spectrum = None

    def radec2lm(self, ra0: float, dec0: float):
        """
        Method to convert source RA and Dec to l, m i.e. image-plane coordinates with respect to phase-tracking centre
        Adapted from https://github.com/wits-cfa/simms
        Args:
            ra0:    RA of phase-tracking centre
            dec0:   dec of phase-tracking centre
        """
        dra = self.ra - ra0
        self.l = np.cos(self.dec) * np.sin(dra) 
        self.m = np.sin(self.dec) * np.cos(dec0) - np.cos(self.dec) * np.sin(dec0) * np.cos(dra)
    
        return self.l, self.m
    
    def set_spectrum(self, freqs: np.ndarray):
        """
        Method to set the source spectrum
        Args:
            freqs:  Array of frequencies at which to evaluate the spectrum
        """
        self.spectrum = (freqs / self.ref_freq) ** self.alpha

        
class CatalogueError(Exception):
    pass


def read_skymodel(input_skymodel):
    sources = []
    with open(input_skymodel) as input_sources:
        for n, line in enumerate(input_sources.readlines()):
            # skip header line 
            if line.startswith("#"):
                continue
            
            # get source info
            source_params = line.strip().split(' ')
            
            try:
                ra, dec, flux, alpha, ref_freq = (
                    source_params[0],
                    source_params[1],
                    float(source_params[2]),
                    float(source_params[3]),
                    float(source_params[4])
                )
            except:
                raise CatalogueError(f"Error reading source {n} in '{input_skymodel}'")
            
            sources.append(Source(ra, dec, flux, alpha, ref_freq))
    
    print(f'RA: {sources[0].ra}, Dec: {sources[0].dec}, Flux: {sources[0].flux}, Alpha: {sources[0].alpha}, Ref freq: {sources[0].ref_freq}')
            

            
            
            
            

            
            


@click.command(command)
@clickify_parameters(config)
def runit(**kwargs):
    opts = OmegaConf.create(kwargs)
    read_skymodel(opts.skymodel)
    # click.echo(f'Hello, {opts.name}!')         