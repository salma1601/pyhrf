import numpy as np
import matplotlib.pyplot as plt

import nibabel
from nipy.modalities.fmri.hemodynamic_models import _hrf_kernel
try:
    from nipy.modalities.fmri.hemodynamic_models import (sample_condition,
                                                         resample_regressor)
except ImportError:
    from nipy.modalities.fmri.hemodynamic_models import _sample_condition as \
        sample_condition
    from nipy.modalities.fmri.hemodynamic_models import _resample_regressor as\
        resample_regressor


def fix_paradigm(paradigm):
    """Fix a paradigm. Force its amplitude to be an array of floats.

    Parameters
    ----------
    paradigm : nipy.modalities.fmri.experimental_paradigm.Paradigm instance.
        The paradigm to fix.
    """
    if not paradigm.amplitude.dtype is float:
        paradigm.amplitude = np.array(paradigm.amplitude, dtype=float)


def compute_prf_regressor(exp_condition, hrf_model, frametimes,
                          prf_model='physio', prf_matrix=None, con_id='cond',
                          oversampling=16, fir_delays=None, normalize=False,
                          plot=False):
    """ Convolve regressors with perfusion response function (PRF).

    Parameters
    ----------
    exp_condition : tuple of three 1D arrays of the same shape
        Descriptor of an experimental condition (onsets, duration, values).

    hrf_model : string
        The hrf model to be used. Can be chosen among: 'spm', 'spm_time',
        'spm_time_dispersion', 'canonical', 'canonical_derivative', 'fir'.

    prf_model : string, optional
        The perfusion response function model to be used. Can be chosen
        among: 'physio', 'hrf'.

    prf_matrix : array, optional
        The physiological matrix that links the PRF to the HRF.

    frametimes : array of shape (n)
        The sought.

    con_id : string, optional
        Identifier of the condition.

    oversampling : int, optional
        Oversampling factor to perform the convolution.

    fir_delays : array-like of int, optional
        Onsets corresponding to the fir basis.

    normalize : bool, optional
        If True, the PRF norm is set to one.

    plot : bool, optional
        If True, HRF and PRF are plotted

    Returns
    -------
    creg : array of shape (n_scans, )
        The computed regressor sampled at frametimes.

    reg_names : string
        The regressor name.

    Notes
    -----
    The different hemodynamic models can be understood as follows:
    'spm': this is the hrf model used in spm
    'spm_time': this is the spm model plus its time derivative (2 regressors)
    'spm_time_dispersion': idem, plus dispersion derivative (3 regressors)
    'canonical': this one corresponds to the Glover hrf
    'canonical with derivative': the Glover hrf + time derivative (2
    regressors)
    'fir': finite impulse response basis, a set of delayed dirac models
    with arbitrary length. This one currently assumes regularly spaced
    frametimes (i.e. fixed time of repetition).
    It is expected that spm standard and Glover model would not yield
    large differences in most cases.
    """
    # this is the average tr in this session, not necessarily the true tr
    tr = float(frametimes.max()) / (np.size(frametimes) - 1)

    # create the high temporal resolution regressor
    hr_regressor, hr_frametimes = sample_condition(
        exp_condition, frametimes, oversampling)

    # get hrf model and keep only the hrf (no time derivatives)
    hkernel = _hrf_kernel(hrf_model, tr, oversampling, fir_delays)
    hkernel = hkernel[0]

    # compute the prf
    if prf_matrix is None:
        prf_matrix = np.eye(hkernel.shape[-1])

    if prf_model == 'physio':
        # TODO: resample the matrix
        pkernel = prf_matrix.dot(hkernel)
    else:
        pkernel = hkernel

    if normalize:
        hkernel /= np.linalg.norm(hkernel)
        pkernel /= np.linalg.norm(pkernel)

    if plot:
        plt.plot(hkernel, label='HRF', marker='.')
        plt.plot(pkernel, label='PRF', marker='.')
        plt.legend()
        plt.show()

    # convolve the regressor and hrf, and downsample the regressor
    conv_reg = np.array([np.convolve(hr_regressor, pkernel)[
                        :hr_regressor.size]])

    # temporally resample the regressor
    creg = resample_regressor(conv_reg, hr_frametimes, frametimes)

    # generate regressor name
    reg_names = ['perfusion']
    return creg, reg_names


def combine_masks(binary_path, probabilistic_path, out_path, threshold=.5):
    """Computes the intersection of a binary mask and a probabilistic mask for
    a given threshold and saves the obtained mask to file. Useful for ASL to
    cut beyond the neck.

    Parameters
    ==========
    binary_path : existant filename
        The binary mask.

    probabilistic_path : existant filename
        The probabilistic mask.

    out_path : filename
        Path to the output mask.

    threshold : float, optional
        The threshold to apply to the probabilistic mask.

    Return
    ======
    out_mask : nibabel.Image
        The output binary mask.
    """
    bin_img = nibabel.load(binary_path)
    bin_data = bin_img.get_data()
    prob_img = nibabel.load(probabilistic_path)
    prob_data = prob_img.get_data()
    if np.any(prob_img.get_affine() != bin_img.get_affine()):
        raise ValueError('binary and probabilistic masks have different '
                         'affines')
    if prob_data.shape != bin_data.shape:
        raise ValueError('binary and probabilistic masks have different '
                         'shapes')

    out_data = bin_data
    out_data[prob_data <= threshold] = 0
    out_data[prob_data > threshold] = 1

    out_img = nibabel.Nifti1Image(out_data, bin_img.get_affine(),
                                  bin_img.get_header())
    nibabel.save(out_img, out_path)
    return out_img