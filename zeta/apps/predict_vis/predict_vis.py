import os
import glob
from omegaconf import OmegaConf
import click
from scabha.schema_utils import clickify_parameters, paramfile_loader
from scabha.basetypes import File
import numpy as np
from astropy.coordinates import Angle
import dask.array as da
from daskms import xds_from_ms, xds_from_table, xds_to_table
from africanus.dft.dask import im_to_vis
from tqdm.dask import TqdmCallback


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

    def set_lm(self, ra0: float, dec0: float):
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

    def set_spectrum(self, freqs: np.ndarray):
        """
        Method to set the source spectrum
        Args:
            freqs:  Array of frequencies at which to evaluate the spectrum
        """
        self.spectrum = (freqs / self.ref_freq) ** self.alpha
        
    def calculate_pixel_coordinates(self, l_coord: np.ndarray, m_coord: np.ndarray):
        """
        Method to calculate pixel coordinates of a source in the image plane
        Args:
            l_coord:    l coordinates of image plane
            m_coord:    m coordinates of image plane
            source:     source object
        """
        self.l_pix_coord = np.argmin(np.abs(l_coord - self.l))
        self.m_pix_coord = np.argmin(np.abs(m_coord - self.m))

        
class CatalogueError(Exception):
    pass


def read_skymodel(input_skymodel, ra0, dec0, freqs, img_size, pix_size):
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
                    Angle(source_params[0]).rad,
                    Angle(source_params[1]).rad,
                    float(source_params[2]),
                    float(source_params[3]),
                    float(source_params[4])
                )
            except:
                raise CatalogueError(f"Error reading source {n} in '{input_skymodel}'")
            
            source = Source(ra, dec, flux, alpha, ref_freq)
            source.set_lm(ra0, dec0)
            source.set_spectrum(freqs)
            sources.append(source)
    
    # create pixel grid
    npix_l, npix_m = img_size, img_size
    npix_tot = npix_l * npix_m
    refpix_l, refpix_m = npix_l // 2, npix_m // 2
    l_coords = np.sort(np.arange(1 - refpix_l, 1 - refpix_l + npix_l) * pix_size)
    m_coords = np.arange(1 - refpix_m, 1 - refpix_m + npix_m) * pix_size
    ll, mm = np.meshgrid(l_coords, m_coords)
    
    # create image hypercube
    intensities = np.zeros((npix_l, npix_m, np.size(freqs), 2))
    
    for m, source in enumerate(sources):
        source.calculate_pixel_coordinates(ll, mm, source.l, source.m)
        # check if source is within image
        if source.l_pix_coord < 0 or source.l_pix_coord >= npix_l or source.m_pix_coord < 0 or source.m_pix_coord >= npix_m:
            print(f"Warning: Source {m} is outside the image grid")
        
        intensities[source.l_pix_coord, source.m_pix_coord, :, 0] += source.flux * source.spectrum
        
    intensities[:, :, :, 1] = intensities[:, :, :, 0] # only Stokes I for now
    
    # reshape arrays for compatibility with im_to_vis
    intensities = intensities.reshape(npix_tot, np.size(freqs), 2)
    lm = np.vstack((ll.flatten(), mm.flatten())).T
    
    # convert arrays to dask arrays
    intensities = da.from_array(intensities, chunks=(npix_tot, 1, 1))
    lm = da.from_array(lm, chunks=(npix_tot, 2))
    
    return intensities, lm

    
@click.command(command)
@clickify_parameters(config)
def runit(**kwargs):
    opts = OmegaConf.create(kwargs)
    
    # read in phase centre
    field_ds  = xds_from_table(f"{ms}::FIELD")[0]
    radec0 = field_ds.PHASE_DIR.data[opts.field_id].compute()
    ra0 = radec0[0][0] 
    dec0 = radec0[0][1]
    
    # read in channel frequencies
    spw_ds = xds_from_table(f"{ms}::SPECTRAL_WINDOW")[0]
    freqs = spw_ds.CHAN_FREQ.data[opts.spwid].compute()
    
    # read in UVW coordinates
    ms_dsl = xds_from_ms(ms, index_cols=["TIME", "ANTENNA1", "ANTENNA2"], chunks={"row":10000}) # consider making chunking dependent on size of dataset
    ms_ds0 = ms_dsl[0]
    uvw = ms_ds0.UVW.data.compute()
    
    # make image and image-plane coordinates
    intensities, lm = read_skymodel(opts.skymodel, ra0, dec0, freqs, opts.img_size, opts.pix_size)
    
    # create computations
    visibilities = []
    for ds in ms_dsl:
        compute_vis = da.blockwise(im_to_vis, ("row", "chan", "corr"), 
                                   intensities, ("lm", "chan", corr), 
                                   ds.UVW.data, ("row", "uvw"), 
                                   lm, ("lm",),
                                   freqs, ("chan",),
                                   dtype=ds.DATA.data.dtype,
                                   concatenate=True)
        visibilities.append(compute_vis)
    
    # create writes
    writes = []
    for n, ds in enumerate(ms_dsl):
        ms_dsl[n] = da.assign(**{
            "MODEL_DATA": ( ("row", "chan", "corr"), visibilities[n] )
        })
        
        writes.append(xds_to_table(ms_dsl, ms, ["MODEL_DATA"]))
        
    # old predict code
    # intensities, lm = read_skymodel(opts.skymodel, ra0, dec0, freqs, opts.img_size, opts.pix_size)
    # vis = im_to_vis(intensities, uvw, lm, freqs)
    
    # perform computations
    with TqdmCallback(desc="compute"):
        da.compute(writes)
    
    